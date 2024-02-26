import threading, queue, time, uuid, logging, yaml, importlib, traceback, sys
import defw_common_def as common
from cdefw_global import *
from defw_exception import DEFwCommError, DEFwError, DEFwInternalError
from cdefw_agent import defw_send_req, defw_send_rsp, defw_connect_to_service, \
			defw_connect_to_client, defw_py_connect_status
from defw import client_agents, service_agents, \
				active_client_agents, active_service_agents, \
				me, preferences, service_apis
import defw

class WorkerEvent:
	EVENT_INCOMING_REQUEST = 1
	EVENT_INCOMING_RESPONSE = 2
	EVENT_CONN_COMPLETE = 3
	EVENT_REFRESH = 4
	EVENT_SHUTDOWN = 5

	def __init__(self, ev_type, connect_status=EN_DEFW_RC_OK, uuid=None, msg=None):
		self.__check_type(ev_type)
		self.ev_type = ev_type
		self.uuid = uuid
		if ev_type == WorkerEvent.EVENT_CONN_COMPLETE:
			self.connect_status = connect_status
		else:
			self.msg_yaml = None
			if msg:
				self.msg_yaml = yaml.load(msg, Loader=yaml.Loader)

	def __check_type(self, we_type):
		if we_type != WorkerEvent.EVENT_INCOMING_REQUEST and \
		   we_type != WorkerEvent.EVENT_INCOMING_RESPONSE and \
		   we_type != WorkerEvent.EVENT_CONN_COMPLETE and \
		   we_type != WorkerEvent.EVENT_REFRESH and \
		   we_type != WorkerEvent.EVENT_SHUTDOWN:
			   raise DEFwError(f"Bad WorkerEvent type {we_type}")

class WorkerRequest:
	WR_SEND_MSG = 1
	WR_CONNECT = 2

	def __init__(self, wr_type, remote_uuid=None,
				 blk_uuid=None, msg=None, ep=None, blocking=True,
				 timeout=preferences['RPC timeout']):
		self.__check_type(wr_type)
		self.wr_type = wr_type
		self.req_uuid = uuid.uuid4()
		self.deadline = time.time() + timeout
		if wr_type == WorkerRequest.WR_SEND_MSG:
			self.remote_uuid = remote_uuid
			self.blk_uuid = blk_uuid
			self.msg = msg
			if not 'req-uuid' in self.msg['rpc']:
				self.msg['rpc']['req-uuid'] = self.req_uuid
		elif wr_type == WorkerRequest.WR_CONNECT:
			self.ep = ep
		self.blocking = blocking
		if blocking:
			self.queue = queue.Queue()
		else:
			self.queue = None

	def __check_type(self, wr_type):
		if wr_type != WorkerRequest.WR_SEND_MSG and \
		   wr_type != WorkerRequest.WR_CONNECT:
			   raise DEFwError(f"Bad Request type {wr_type}")

	def wait(self):
		if not self.queue:
			return None

		t = time.time()
		event = None
		while t < self.deadline:
			try:
				event = self.queue.get(timeout=1)
				break
			except queue.Empty:
				pass
			t = time.time()
			logging.debug(f"cur time {str(t)}, deadline {str(self.deadline)}")
		if event and event.ev_type != WorkerEvent.EVENT_SHUTDOWN:
			if event.ev_type == WorkerEvent.EVENT_CONN_COMPLETE:
				return event.connect_status
			return event.msg_yaml
		raise DEFwCommError('Response timed out')

	def get_uuid(self):
		return self.req_uuid

	def get_uuid_str(self):
		return str(self.req_uuid)

# Can add a req
class WorkerThread:
	def __init__(self):
		self.queue = queue.Queue()
		self.thread = threading.Thread(target=self.handle, args=())
		self.thread.start()
		self.req_db = {}
		self.req_db_lock = threading.Lock()

	def put_ev(self, we):
		self.queue.put(we)
		if we.EVENT_SHUTDOWN:
			self.thread.join()

	def add_work_request(self, work_request):
		with self.req_db_lock:
			self.req_db[work_request.get_uuid()] = work_request

	def refresh_agents(self, *args, **kwargs):
		try:
			client_agents.reload()
			service_agents.reload()
			active_client_agents.reload()
			active_service_agents.reload()
			logging.debug(f"Refreshed agent lists {me.is_resmgr()}")

			if not me.is_resmgr():
				if 'Resource Manager' in service_apis:
					defw.resmgr = service_apis['Resource Manager'].service_classes[0] \
						(ep=active_service_agents.get_resmgr())
					logging.debug(f"Created resource manager API: {defw.resmgr}")
					from defw import updater_queue
					updater_queue.put({'type': 'resmgr', 'resmgr': defw.resmgr})
		except Exception as e:
			logging.critical("Couldn't refresh agents")
			raise e

	def spawn_temporary_worker(self, cb, *args, **kwargs):
		tmp_thread = threading.Thread(target=cb, args=args, kwargs=kwargs)
		tmp_thread.start()

	# This thread should never do any blocking calls
	def handle(self):
		shutdown = False
		while not shutdown:
			try:
				we = self.queue.get(timeout=1)
			except queue.Empty:
				continue

			logging.debug(f"Received event {we.ev_type}")

			if we.ev_type == WorkerEvent.EVENT_INCOMING_REQUEST:
				logging.debug(f"handling request {we.msg_yaml}")
				self.spawn_temporary_worker(self.handle_rpc_req, we.msg_yaml, we.uuid)
			elif we.ev_type == WorkerEvent.EVENT_INCOMING_RESPONSE:
				# find request
				logging.debug(f"handling response {we.msg_yaml}")
				try:
					with self.req_db_lock:
						wr = self.req_db[we.msg_yaml['rpc']['req-uuid']]
					wr.queue.put(we)
				except:
					with self.req_db_lock:
						logging.critical(f"Unmatched response. DB = {self.req_db}")
			elif we.ev_type == WorkerEvent.EVENT_REFRESH:
				logging.debug("Refreshing Agents")
				self.spawn_temporary_worker(self.refresh_agents)
			elif we.ev_type == WorkerEvent.EVENT_CONN_COMPLETE:
				try:
					with self.req_db_lock:
						wr = self.req_db[we.uuid]
					wr.queue.put(we)
				except:
					with self.req_db_lock:
						logging.critical(f"Unmatched response. DB = {self.req_db}")
			elif we.ev_type == WorkerEvent.EVENT_SHUTDOWN:
				logging.debug("Shutting down thread")
				shutdown = True
				# shutdown any waiting events
				with self.req_db_lock:
					for k, v in self.req_db.items():
						v.queue.put(WorkerEvent.EVENT_SHUTDOWN)
			else:
				logging.critical(f"Bug. Unknown event {we.ev_type}")

	def handle_rpc_req(self, y, blk_uuid):
		function_name = ''
		class_name = ''
		method_name = ''
		rc = {}

		logging.critical("Calling handle_rpc_type")

		# check to see if this is for me
		target = y['rpc']['dst']
		if not target == me.my_endpoint():
			logging.debug("Message is not for me")
			logging.debug(target)
			logging.debug(me.my_endpoint())
			return
		logging.critical("after check")
		source = y['rpc']['src']
		hostname = source.hostname
		logging.critical("after check 3")
		mname = y['rpc']['module']
		logging.critical("after check 4")
		rpc_type = y['rpc']['type']
		logging.critical("after check 5")
		if rpc_type == 'function_call':
			function_name = y['rpc']['function']
		elif rpc_type == 'method_call':
			class_name = y['rpc']['class']
			method_name = y['rpc']['method']
			class_id = y['rpc']['class_id']
			#TODO: If you're the resource manager don't instantiate
			# a new class return the object which is already instantiated
			# on startup. This way all the state is maintained there.
			# We can add the resmgr instance with with key class_id.
			# Don't ever delete the resmgr.
			#
			# is this true of all services? Or are services stateless. So
			# if multiple clients connect to it, then do you want
			# a separate instance per service, or do you want one instance
			# for all clients trying to request work?
			#
		elif rpc_type == 'instantiate_class' or rpc_type == 'destroy_class':
			class_name = y['rpc']['class']
			class_id = y['rpc']['class_id']
			logging.debug(f"instantiate_class {class_name} with {class_id}")
		else:
			raise DEFwError('Unexpected rpc')

		# any remote invocation implies that module which needs to be
		# imported is in the python/icpa-be/
		logging.critical("module name is: %s " % mname)
		logging.critical("rpc type is: %s " % rpc_type)
		module = importlib.import_module(mname)
		importlib.reload(module)
		logging.debug(f"module is: {dir(module)}")
		args = y['rpc']['parameters']['args']
		kwargs = y['rpc']['parameters']['kwargs']
		defw_exception_string = None
		try:
			if rpc_type == 'function_call':
				module_func = getattr(module, function_name)
				if hasattr(module_func, '__call__'):
					rc = module_func(*args, **kwargs)
			elif rpc_type == 'instantiate_class':
				if me.is_resmgr() and class_name == 'DEFwResMgr':
					common.add_to_class_db(defw.resmgr, class_id)
				else:
					my_class = getattr(module, class_name)
					# TODO: Instantiating a class can result in a blockinh
					# call
					instance = my_class(*args, **kwargs)
					common.add_to_class_db(instance, class_id)
			elif rpc_type == 'destroy_class':
				if me.is_resmgr() and class_name == 'DEFwResMgr':
					common.del_entry_from_class_db(class_id)
				else:
					instance = common.get_class_from_db(class_id)
					del(instance)
					common.del_entry_from_class_db(class_id)
			elif rpc_type == 'method_call':
				instance = common.get_class_from_db(class_id)
				if type(instance).__name__ != class_name:
					raise DEFwError(f"requested class {class_name}, "  \
								   f"but id refers to class {type(instance).__name__}")
				rc = getattr(instance, method_name)(*args, **kwargs)
		except Exception as e:
			if type(e) == DEFwError:
				defw_exception_string = e
			else:
				exception_list = traceback.format_stack()
				exception_list = exception_list[:-2]
				exception_list.extend(traceback.format_tb(sys.exc_info()[2]))
				exception_list.extend(traceback.format_exception_only(sys.exc_info()[0],
														sys.exc_info()[1]))
				header = "Traceback (most recent call last):\n"
				stacktrace = "".join(exception_list)
				defw_exception_string = header+stacktrace
		if defw_exception_string:
			rc_yaml = common.populate_rpc_rsp(target, source, rc, defw_exception_string)
		else:
			rc_yaml = common.populate_rpc_rsp(target, source, rc)
		rc_yaml['rpc']['req-uuid'] = y['rpc']['req-uuid']

		wr = WorkerRequest(WorkerRequest.WR_SEND_MSG,
						   remote_uuid=source.remote_uuid,
						   blk_uuid=blk_uuid, msg=rc_yaml, blocking=False)
		rc = send_rsp(wr)
		return rc

worker_thread = WorkerThread()

def put_shutdown():
	we = WorkerEvent(WorkerEvent.EVENT_SHUTDOWN)
	worker_thread.put_ev(we)
	from defw import updater_queue
	updater_queue.put({'type': 'shutdown'})
	# TODO need to uninitialize all active services

def put_request(msg, uuid):
	try:
		we = WorkerEvent(WorkerEvent.EVENT_INCOMING_REQUEST,
						 uuid=uuid, msg=msg)
		worker_thread.put_ev(we)
	except:
		logging.critical(f"Recieved a bad request:\n{msg}")

def put_response(msg, uuid):
	try:
		we = WorkerEvent(WorkerEvent.EVENT_INCOMING_RESPONSE,
						 uuid=uuid, msg=msg)
		worker_thread.put_ev(we)
	except:
		logging.critical(f"Recieved a bad response:\n{msg}")

def put_refresh():
	we = WorkerEvent(WorkerEvent.EVENT_REFRESH)
	worker_thread.put_ev(we)

def put_connect_complete(status, uuid_str):
	we = WorkerEvent(WorkerEvent.EVENT_CONN_COMPLETE,
					 connect_status=status, uuid=uuid.UUID(uuid_str))
	worker_thread.put_ev(we)

def send_rsp(wr):
	rc = defw_send_rsp(wr.remote_uuid,
					  wr.blk_uuid,
					  yaml.dump(wr.msg))
	return rc

def send_req(wr):
	if wr.blocking:
		worker_thread.add_work_request(wr)

	# non-blocking send
	rc = defw_send_req(wr.remote_uuid,
					  wr.blk_uuid,
					  yaml.dump(wr.msg))

	if rc:
		raise DEFwCommError(f"Sending failed with {defw_rc2str(rc)}")

	if wr.blocking:
		return wr.wait()

	return rc, None

def connect_to_agent(wr):
	if wr.blocking:
		worker_thread.add_work_request(wr)

	if wr.ep.is_service():
		func = defw_connect_to_service
	else:
		func = defw_connect_to_client
	# TODO: need to figure out how to pass function pointers
	rc = func(wr.ep.addr,
			  wr.ep.listen_port,
			  wr.ep.name,
			  wr.ep.hostname,
			  wr.ep.node_type,
			  wr.get_uuid_str(),
			  None)
	if rc and rc != EN_DEFW_RC_IN_PROGRESS:
		raise DEFwError("Failed to connect:", defw_rc2str(rc))

	if wr.blocking:
		return wr.wait()

	return rc, None

