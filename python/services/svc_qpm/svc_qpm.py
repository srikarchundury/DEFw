from defw_agent_info import *
from defw_util import prformat, fg, bg, expand_host_list
from defw import me
import logging, uuid, time, queue, threading, logging, yaml
from defw_exception import DEFwError, DEFwNotReady
import sys, os, re, math

sys.path.append(os.path.split(os.path.abspath(__file__))[0])
import qpm_common as common


CID_COUNTER = 0
QCR_VERBOSE = 1

class CircuitStates:
	UNDEF = 0
	READY = 1
	RUNNING = 2
	MARKED_FOR_DELETION = 3
	DONE = 4

class QRCInstance:
	STATUS_UNKNOWN = 1
	STATUS_CONNECTED = 2

	def __init__(self, pid, name, qrc=None):
		self.instance = qrc
		self.name = name
		self.circuit_results = []
		self.load = 0
		self.pid = pid
		self.status = QRCInstance.STATUS_UNKNOWN
		self.ep = None

	def add_qrc(self, qrc):
		self.instance = qrc

class Circuit:
	def __init__(self, cid, info):
		self.__state = CircuitStates.UNDEF
		self.__cid = cid
		self.info = info
		self.assigned_qrc = None
		self.setup_circuit_run_details()

	def round_to_nearest_power_of_two(self, number):
		if number <= 0:
			return 0  # or handle the case as needed

		nearest_power_of_two = 2 ** int(math.log2(number) + 0.5)
		return nearest_power_of_two

	def setup_circuit_run_details(self):
		# TODO: Make MPI configuration decisions based
		# on the circuit meta data

		try:
			self.info['exec'] = os.environ['QFW_LAUNCHER_BIN']
		except:
			self.info['exec'] = 'mpirun'

		try:
			# QFW_MODULE_USE_PATH is in the format:
			#	path/to/use1:path/to/use2:...
			module_use = os.environ['QFW_MODULE_USE_PATH']
			self.info['modules'] = {'use': module_use.split(':')}
			# QFW_MODULE_LOADS is in the format:
			#	mod1,mod2,...
			mods = os.environ['QFW_MODULE_LOADS']
			self.info['modules']['mods'] =  mods.split(',')
		except:
			self.info['modules'] = {}
			self.info['modules']['use'] = ''
			self.info['modules']['mods'] = ''

		self.info['provider'] = 'shm+cxi:linkx'
		self.info['mapping'] = 'ppr:1:l3cache'
		try:
			self.info['qfw_circuit_runner_path'] = os.environ['QFW_CIRCUIT_RUNNER_PATH']
		except:
			self.info['qfw_circuit_runner_path'] = 'circuit_runner'
		try:
			self.info['qfw_dvm_uri_path'] = \
				f"file:{os.environ['QFW_DVM_URI_PATH']}"
		except:
			self.info['qfw_dvm_uri_path'] = 'search'

		# each 10 qubits requires 1 node added to the simulation
		np = int(self.info['num_qubits'] / 10)
		if np < 1:
			np = 1
		else:
			np = self.round_to_nearest_power_of_two(np)
		self.info['np'] = np
		logging.debug(f"Setting number of processes to: {self.info['np']}")

	def getState(self):
		return self.__state

	def set_state(self, state):
		# State is monotonically increasing
		if self.__state > state:
			return False
		self.__state = state
		return True

	def set_ready(self):
		return self.set_state(CircuitStates.READY)

	def set_running(self):
		return self.set_state(CircuitStates.RUNNING)

	def set_deletion(self):
		return self.set_state(CircuitStates.MARKED_FOR_DELETION)

	def set_done(self):
		self.assigned_qrc = None
		return self.set_state(CircuitStates.DONE)

	def can_delete(self):
		if self.__state <= CircuitStates.READY:
			return True
		return False

	def status(self):
		if self.__state == CircuitStates.READY:
			return 'READY'
		if self.__state == CircuitStates.RUNNING:
			return 'RUNNING'
		if self.__state == CircuitStates.MARKED_FOR_DELETION:
			return 'DELETING'
		if self.__state == CircuitStates.DONE:
			return 'DONE'
		return 'BUG'

class QPM:
	def __init__(self, start=True):
		self.circuits = {}
		self.runner_queue = queue.Queue()
		self.circuit_results = []
		self.qrc_rr = 0
		self.free_hosts = expand_host_list(os.environ['QFW_QPM_ASSIGNED_HOSTS'])
		self.inuse_hosts = []

	def parse_result(self, result):
		i = 0
		ob = 0
		b = 0
		lines = result.split('\n')
		for l in lines:
			if len(l.strip()) > 0 and l.strip()[0] == '#':
				b += 1
				continue
			i += 1
			if "{" in l:
				ob += 1
			elif "}" in l:
				ob -= 1
			if ob == 0:
				break

		res = "\n".join(lines[b:i+1])
		circ_result = yaml.safe_load(res)

		all_stats = []
		while True:
			stats_dict = {}
			ob = 0
			j = 0
			for l in lines[i:]:
				j += 1
				if "#MSG(TAL-SH" in l:
					ob += 1
				elif "#END_MSG" in l:
					ob -= 1
				if ob == 0:
					break
			stats = "\n".join(lines[i:i+j-1])
			blk = lines[i:i+j-1]
			if len(blk):
				for e in blk:
					kv = [ss for ss in e.split(':') if ss.strip()]
					if len(kv) > 2:
						stats_dict[kv[-1].strip()] = "----"
					if len(kv) == 2:
						stats_dict[kv[0].strip()] = kv[1].strip()
				all_stats.append(stats_dict)
			i = i+j
			if i >= len(lines):
				break
		return circ_result, all_stats

	def create_circuit(self, info):
		if not common.g_qpm_initialized:
			#raise DEFwNotReady("QPM has not initialized properly")
			raise RuntimeError("QPM has not initialized properly")

		cid = str(uuid.uuid4())
		self.circuits[cid] = Circuit(cid, info)
		self.circuits[cid].set_ready()
		return cid

	def delete_circuit(self, cid):
		if cid not in self.circuits:
			return
		circ = self.circuits[cid]
		if circ.can_delete():
			del self.circuits[cid]
		else:
			circ.set_deletion()

	def consume_resources(self, circ):
		info = circ.info
		num_hosts = int(info['np'] / 8)
		if not num_hosts:
			num_hosts = 1

		# determine if we have enough hosts to run this circuit
		# If the number of hosts required is more than the total number
		# of hosts then we can't run the circuit.
		if num_hosts > len(self.free_hosts):
			raise DEFwOutOfResources("Not enough nodes to run simulation")

		circ.info['hosts'] = self.free_hosts[:num_hosts]
		logging.debug(f"Setting up MPI to run on {info['np']} {num_hosts} {circ.info['hosts']}")
		self.inuse_hosts += self.free_hosts[:num_hosts]
		self.free_hosts = self.free_hosts[num_hosts:]
		qrc = common.QRC_list[self.qrc_rr % len(common.QRC_list)]
		qrc.load += 1
		self.qrc_rr += 1
		circ.assigned_qrc = qrc

	def free_resources(self, circ):
		circ_hosts = circ.info['hosts']
		for h in circ_hosts:
			self.inuse_hosts.remove(h)
			self.free_hosts.append(h)
		if circ.assigned_qrc:
			circ.assigned_qrc.load -= 1
		circ.set_done()

	def common_run(self, cid):
		self.read_all_qrc_cqs()
		circuit = self.circuits[cid]
		self.consume_resources(circuit)
		logging.debug(f"Running {cid}\n{circuit.info}")
		return circuit

	def sync_run(self, cid):
		if not common.g_qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = self.common_run(cid)
		try:
			rc, output = circuit.assigned_qrc.instance.sync_run(cid, circuit.info)
		except Exception as e:
			self.free_resources(circuit)
			raise e
		self.free_resources(circuit)
		circ_result, stats = self.parse_result(output.decode('utf-8'))
		logging.debug(f"Circuit results = {circ_result}")
		logging.debug(f"stats = {stats}")
		return rc, circ_result, stats

	def async_run(self, cid):
		if not common.g_qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = self.common_run(cid)

		try:
			circuit.assigned_qrc.instance.async_run(cid, circuit.info)
		except Exception as e:
			self.free_resources(circuit)
			raise e

	def read_all_qrc_cqs(self):
		for qrc in common.QRC_list:
			while (res := qrc.instance.read_cq()):
				qrc.circuit_results.append(res)
				circ = self.circuit[res['cid']]
				self.free_resources(circ)

	def read_cq(self, cid=None):
		if not common.g_qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		self.read_all_qrc_cqs()
		if cid:
			if cid not in self.circuits:
				return None
			circ = self.circuits[cid]
			qrc = circ.assigned_qrc
			i = 0
			for e in qrc.circuit_results:
				if cid == e['cid']:
					r = qrc.circuit_results.pop(i)
					return r
				i += 1
		else:
			for qrc in common.QRC_list:
				if len(qrc.circuit_results) > 0:
					r = qrc.circuit_results.pop(0)
					return r
		return None

	def peek_cq(self, cid=None):
		if not common.g_qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		self.read_all_qrc_cqs()
		if cid:
			if cid not in self.circuits:
				return None
			circ = self.circuits[cid]
			qrc = circ.assigned_qrc
			i = 0
			for e in qrc.circuit_results:
				if cid == e['cid']:
					return e
				i += 1
		else:
			for qrc in common.QRC_list:
				if len(qrc.circuit_results) > 0:
					return qrc.circuit_results[0]
		return None

	def status(self, cid):
		if not common.g_qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		self.read_all_qrc_cqs()
		r = {}
		for cid, circ in self.circuits.items():
			r[cid] = circ.status()
		return r

	def is_ready(self):
		return common.g_qpm_initialized

	def query(self):
		from . import svc_info
		cap = Capability(svc_info['name'], svc_info['description'], 1)
		svc = ServiceDescr(svc_info['name'], svc_info['description'], [cap], 1)
		info = DEFwAgentInfo(self.__class__.__name__,
						  self.__class__.__module__, [svc])
		return info

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services=None):
		pass

	def schedule_shutdown(self, timeout=5):
		logging.debug(f"Shutting down in {timeout} seconds")
		time.sleep(timeout)
		me.exit()

	def shutdown(self):
		logging.debug("Scheduling QPM Shutdown")
		ss = threading.Thread(target=self.schedule_shutdown, args=())
		ss.start()

	def test(self):
		return "****QPM Test Successful****"

