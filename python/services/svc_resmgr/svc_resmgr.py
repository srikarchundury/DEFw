"""
Interface module for the Resource Manager
"""
from defw_agent_info import *
from defw_agent import Endpoint
from defw import me, active_service_agents, active_client_agents, \
					service_agents, client_agents, defw_config_yaml
from defw_agent_baseapi import BaseAgentAPI
from defw_exception import DEFwError,DEFwCommError,DEFwAgentNotFound,\
						  DEFwInternalError,DEFwRemoteError,DEFwReserveError, \
						  DEFwInProgress
from defw_util import prformat, fg, bg
import logging, uuid, time, yaml, threading

# Agent states

# Agent has connected but not registered
AGENT_STATE_CONNECTED = 1 << 0
# Agent connected and registered
AGENT_STATE_REGISTERED = 1 << 1
# Agent connected has registered previously but now has unregistered
AGENT_STATE_UNREGISTERED = 1 << 2
# Agent is in error state
AGENT_STATE_ERROR = 1 << 3

class DEFwResMgr:
	SVC = 'services'
	ACTV_SVC = 'active services'
	CLT = 'clients'
	ACTV_CLT = 'active clients'
	def __init__(self, sql_path):
		self.__db_lock = threading.Lock()
		self.__services_db = {}
		self.__clients_db = {}
		self.__active_services_db = {}
		self.__active_clients_db = {}
		self.__dbs = {DEFwResMgr.SVC: self.__services_db,
					  DEFwResMgr.ACTV_SVC: self.__active_services_db,
					  DEFwResMgr.CLT: self.__clients_db,
					  DEFwResMgr.ACTV_CLT: self.__active_clients_db}
		self.__my_ep = me.my_endpoint()
		self.__reload_resources(query=True)

	def __grab_agent_info(self, agent_dict, db, skip_self=False, query=True):
		for k, agent in agent_dict.items():
			ep = agent.get_ep()
			if ep == self.__my_ep and skip_self:
				continue
			client_api = BaseAgentAPI(target=ep)
			aname = ep.get_id()
			svc_info = []
			if query:
				svc_info = client_api.query()
			logging.debug(f"examining -- {aname}")
			with self.__db_lock:
				if aname in db:
					logging.debug(f"{aname} is already in the {db}")
					continue
				db[aname] = \
					{'agent': agent,
					'api': client_api,
					'info': svc_info}
				if not 'state' in db[aname]:
					logging.debug(f"Setting {aname} stat to CONNECTED")
					db[aname]['state'] = AGENT_STATE_CONNECTED

				for i in db[aname]['info']:
					i.add_key(aname)
					if db == self.__services_db:
						i.add_loc_db(DEFwResMgr.SVC)
					elif db == self.__active_services_db:
						i.add_loc_db(DEFwResMgr.ACTV_SVC)
					elif db == self.__clients_db:
						i.add_loc_db(DEFwResMgr.CLT)
					elif db == self.__active_clients_db:
						i.add_loc_db(DEFwResMgr.ACTV_CLT)

	def __reload_resources(self, query=True):
		self.__grab_agent_info(client_agents, self.__clients_db, query=query)
		# TODO: I'm disabling the resmgr trying to query itself for now.
		# Figure out how to properly handle this
		#
		self.__grab_agent_info(active_client_agents, self.__active_clients_db, query=query)
		self.__grab_agent_info(service_agents, self.__services_db, skip_self=True, query=query)
		self.__grab_agent_info(active_service_agents, self.__active_services_db,
						 skip_self=True, query=query)

	def unset_state(self, db, aid, state):
		with self.__db_lock:
			db[aid]['state'] = \
				db[aid]['state'] & ~state

	def set_state(self, db, aid, state):
		with self.__db_lock:
			db[aid]['state'] = \
				db[aid]['state'] | state

	def get_state(self, db, aid):
		with self.__db_lock:
			return db[aid]['state']

	def __register(self, global_agent_dict, local_agent_dict, ep, info, query=True):
		agent = global_agent_dict.get_agent(ep)
		self.__reload_resources(query)
		if not agent:
			if ep.name in local_agent_dict:
				self.set_state(local_agent_dict, ep.get_id(), AGENT_STATE_ERROR)
			logging.debug(f"Registration from an unknown client {ep}, {global_agent_dict}")
			logging.debug(f"Dict size: {global_agent_dict.get_num_connected_agents()}")
			for k, agent in global_agent_dict.items():
				logging.debug(f"agent {k} - {agent.get_ep()}")
			raise DEFwAgentNotFound(f"Registration from an unknown client {ep}, {global_agent_dict}")
		else:
			self.set_state(local_agent_dict, ep.get_id(), AGENT_STATE_REGISTERED)
		return

	def __deregister(self, global_agent_dict, local_agent_dict, ep):
		agent = global_agent_dict.get_agent(ep)
		if not agent:
			raise DEFwAgentNotFound(f"Deregistration from an unknown client {ep}, {global_agent_dict}")
		else:
			self.unset_state(local_agent_dict, ep.get_id(), AGENT_STATE_REGISTERED)

	"""
	Register a client with the Resource Manager

	Args:
		client_ep (endpoint): Client endpoint

	Returns:
		None

	Raises:
		DEFwCommError: If Resource Manager is not reachable
	"""
	def register_agent(self, ep, context=None):
		logging.debug(f"Agent with ep {ep} registering. Current Agents in the system")
		client_agents.dump()
		self.__register(client_agents, self.__clients_db, ep, context, query=False)
		self.__clients_db[ep.get_id()]['context'] = context
		state = self.get_state(self.__clients_db, ep.get_id())
		logging.debug(f"Agent with ep {ep} has registered. Now in State {state}")

	def deregister_agent(self, ep):
		logging.debug(f"Agent with ep {ep} deregistering")
		self.__deregister(client_agents, self.__clients_db, ep)

	def ready_agents(self):
		try:
			total = int(defw_config_yaml['defw']['expected-agent-count'])
		except Exception as e:
			raise DEFwInternalError(f"Bad configuration: {yaml.dump(defw_config_yaml)}")
		registered = 0
		with self.__db_lock:
			for agent, info in self.__clients_db.items():
				logging.debug(f"{agent} is in state {info['state']}")
				if info['state'] & AGENT_STATE_REGISTERED:
					registered += 1
		if (total <= registered):
			return True
		raise DEFwInProgress(f"Missing clients. Expected {total}, registered {registered}")

	def wait_agents(self, timeout = 10):
		start = time.time()
		while True:
			if time.time() - start > timeout:
				raise DEFwCommError("Agents failed to connect to resource manager")
			try:
				if self.ready_agents():
					break
			except Exception as e:
				if type(e) == DEFwInProgress:
					continue
				else:
					raise e
		logging.debug(f"wait_agents complete: {self.__clients_db}")

	def dereg_agents(self):
		registered = 0
		with self.__db_lock:
			for agent, info in self.__clients_db.items():
				if info['state'] & AGENT_STATE_REGISTERED:
					registered += 1
		logging.debug(f"Agents still registered = {registered}")
		if (registered > 0):
			raise DEFwInProgress(f"Clients still registered {registered}")

	def wait_agents_deregistration(self, timeout = 10):
		start = time.time()
		while True:
			if time.time() - start > timeout:
				raise DEFwCommError("Agents failed to deregister from resource manager")
			try:
				self.dereg_agents()
				break
			except Exception as e:
				if type(e) == DEFwInProgress:
					continue
				else:
					raise e
		logging.debug(f"wait for agent deregistration complete: {self.__clients_db}")

	def get_agents_context(self):
		contexts = {}
		logging.debug(f"Currently registered: {self.__clients_db}")
		num_clients = 0
		with self.__db_lock:
			num_clients = len(self.__clients_db)
			for k, v in self.__clients_db.items():
				agent = v['agent']
				contexts[agent.get_pid()] = v['context']
		num_contexts = len(contexts)
		if num_contexts != num_clients:
			raise DEFwNotFound("Clients didn't register properly. "\
					"Found {num_contexts}. Expected {num_clients}")
		return dict(sorted(contexts.items()))

	"""
	Register a service with the Resource Manager

	Args:
		client_ep (endpoint): service endpoint

	Returns:
		agent: An agent class instance which references the service

	Raises:
		DEFwCommError: If Resource Manager is not reachable
	"""
	def register_service(self, service_ep, context=None):
		self.__register(service_agents, self.__services_db, ep, context)

	"""
	De-register an agent

	Args:
		agent (Agent): Agent instance to deregister

	Returns:
		None

	Raises:
		DEFwCommError: If Resource Manager is not reachable
		DEFwAgentNotFound: If agent is not registered
	"""
	def deregister(self, ep):
		if ep.name not in self.__clients_db and \
		   ep.name not in self.__services_db:
			   raise DEFwAgentNotFound(f"agent {ep.name} not found")
		if ep.name in self__services_db:
			self.__services_db[ep.name]['api'].unregister()
			del self.__services_db[ep.name]
		else:
			self.__clients_db[ep.name]['api'].unregister()
			del self.__clients_db[ep.name]
		return

	def get_info(self, db, svc_name, svc_type, svc_caps):
		r = []
		for k, v in db.items():
			if not v['info']:
				continue

			for i in v['info']:
				if i.is_match(svc_name, svc_type, svc_caps):
					r.append(i)
				else:
					logging.debug(f"No match found with ({svc_name}, {svc_type}, {svc_caps}")

		return r

	"""
	List all available Agents in the DEFw Network

	Args:
		service_filter: a string to filter services on

	Returns:
		dict: dictionary of services available on each agent

	Raises:
		DEFwCommError: If Resource Manager is not reachable
	"""
	def get_services(self, svc_name, svc_type=-1, svc_caps=-1):
		logging.debug(f"get_services({svc_name}, {svc_type}, {svc_caps})")
		all_info = []
		self.__reload_resources(query=True)
		all_info += self.get_info(self.__active_services_db, svc_name, svc_type, svc_caps)
		all_info += self.get_info(self.__services_db, svc_name, svc_type, svc_caps)
		logging.debug(f"all_info({all_info})")
		return all_info

	"""
	Reserve an Agent which exists on the DEFw Network

	Args:
		servics (dict): Dictionary of services to reserve

	Returns:
		endpoint list of all services reserved

	Raises:
		DEFwCommError: If Resource Manager is not reachable
		DEFwReserveError: If there is an error in the reservation process
	"""
	def reserve(self, client_ep, service_infos, *args, **kwargs):
		svc_eps = []
		for service_info in service_infos:
			db = self.__dbs[service_info.get_loc_db()]
			with self.__db_lock:
				db_key = service_info.get_key()
				entry = db[db_key]
			if not entry['state'] & AGENT_STATE_REGISTERED:
				DEFwReserveError(f"Agent {db_key} is not registered")
			service_info.consume_capacity()
			api = entry['api']
			try:
				api.reserve(service_info,  client_ep, *args, **kwargs)
			except Exception as e:
				raise DEFwReserveError(str(e))
			ep = entry['agent'].get_ep()
			# if this is a remote endpoint we should NULL out the blk_uuid
			# because it wouldn't mean anything here.
			if ep.remote_uuid != me.my_uuid():
				ep.blk_uuid = str(uuid.UUID(int=0))
			svc_eps.append(entry['agent'].get_ep())
		return svc_eps

	"""
	Release a reserved Agent

	Args:
		servics (dict): Dictionary of services to release

	Returns:
		None

	Raises:
		DEFwCommError: If Resource Manager is not reachable
		DEFwReserveError: If there is an error in the release process
	"""
	def release(self, service_infos):
		for service_info in service_infos:
			db = self.__dbs[service_info.get_loc_db()]
			with self.__db_lock:
				db_key = service_info.get_key()
				entry = db[db_key]
			if not entry['state'] & AGENT_STATE_REGISTERED:
				DEFwReserveError("Agent is not registered")
			services = service_info.get_services()
			for svc in services:
				svc.release_capacity()
			api = entry['api']
			try:
				api.release()
			except Exception as e:
				raise DEFwReserveError(str(e))

	def query(self):
		from . import SERVICE_NAME, SERVICE_DESC
		from api_resmgr import ResMgrType, ResMgrCapability
		from defw_agent_info import get_bit_list, get_bit_desc, \
									Capability, DEFwServiceInfo
		t = get_bit_list(ResMgrType.RESMGR_TYPE_DEFW, ResMgrType)
		c = get_bit_list(ResMgrCapability.RESMGR_CAP_DEFW, ResMgrCapability)
		cap = Capability(ResMgrType.RESMGR_TYPE_DEFW,
						ResMgrCapability.RESMGR_CAP_DEFW, get_bit_desc(t, c))
		info = DEFwServiceInfo(SERVICE_NAME, SERVICE_DESC,
							   self.__class__.__name__,
							   self.__class__.__module__,
							   cap, -1)
		return info

