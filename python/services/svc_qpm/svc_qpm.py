from defw_agent_info import *
from defw_util import expand_host_list, round_half_up, round_to_nearest_power_of_two
from defw import me
import logging, uuid, time, queue, threading, logging, yaml
from defw_exception import DEFwError, DEFwNotReady, DEFwInProgress
import sys, os, re, math, psutil
from defw_proc import Process
from .svc_qrc import QRC
sys.path.append(os.path.split(os.path.abspath(__file__))[0])
print(os.path.split(os.path.abspath(__file__))[0])
import qpm_common as common


# Maximum number of processes per node
MAX_PPN = 8
# Maximum number of qubits per process
MAX_QUBITS_PP = 10

class CircuitStates:
	UNDEF = 0
	MARKED_FOR_DELETION = 1
	DONE = 2
	READY = 3
	RUNNING = 4

class Circuit:
	def __init__(self, cid, info):
		self.__state = CircuitStates.UNDEF
		self.__cid = cid
		self.info = info
		self.assigned_qrc = None
		self.setup_circuit_run_details()

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
		#self.info['mapping'] = 'ppr:1:l3cache'
		self.info['mapping'] = 'l3cache:pe=6'
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
		np = round_half_up(self.info['num_qubits'] / MAX_QUBITS_PP)
		if np < 1:
			np = 1
		else:
			np = round_to_nearest_power_of_two(np)
		self.info['np'] = np
		logging.debug(f"Setting number of processes to: {self.info['np']} " \
					  f"for num qubits: {self.info['num_qubits']}")

	def getState(self):
		return self.__state

	def get_cid(self):
		return self.__cid

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
		logging.debug("Creating the QRC")
		self.qrc = QRC()
		self.free_hosts = {}
		self.setup_host_resources()

	def setup_host_resources(self):
		hl = expand_host_list(os.environ['QFW_QPM_ASSIGNED_HOSTS'])
		for h in hl:
			comp = h.split(':')
			if len(comp) == 1:
				self.free_hosts[comp[0]] = MAX_PPN
			elif len(comp) == 2:
				self.free_hosts[comp[0]] = int(comp[1])

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
		try:
			circ_result = yaml.safe_load(res)
		except:
			return res, {}

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
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		cid = str(uuid.uuid4())
		self.circuits[cid] = Circuit(cid, info)
		self.circuits[cid].set_ready()
		logging.debug(f"{cid} added to circuit database")
		return cid

	def delete_circuit(self, cid):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		if cid not in self.circuits:
			return
		circ = self.circuits[cid]
		if circ.can_delete():
			del self.circuits[cid]
		else:
			circ.set_deletion()

	def consume_resources(self, circ):
		info = circ.info
		np = info['np']
		num_hosts = int(np / MAX_PPN)
		if not num_hosts:
			num_hosts = 1

		# determine if we have enough hosts to run this circuit
		# If the number of hosts required is more than the total number
		# of hosts then we can't run the circuit.
		logging.debug(f"Available resources = {self.free_hosts}")
		if num_hosts > len(self.free_hosts.keys()):
			raise DEFwOutOfResources("Not enough nodes to run simulation")

		tmp_resources = {}
		consumed_res = {}
		itrnp = 0
		for host in self.free_hosts.keys():
			if np == 0:
				break;
			tmp_resources[host] = self.free_hosts[host]
			if self.free_hosts[host] >= np:
				self.free_hosts[host] = self.free_hosts[host] - np
				consumed_res[host] = np
				itrnp += np
				np = 0
			elif self.free_hosts[host] < np and self.free_hosts[host] != 0:
				np -= self.free_hosts[host]
				itrnp += self.free_hosts[host]
				consumed_res[host] = self.free_hosts[host]
				self.free_hosts[host] = 0
		if np != 0:
			# restore whatever was consumed
			for k, v in tmp_resources.items():
				self.free_hosts[k] = v
			raise DEFwOutOfResources("Not enough nodes to run simulation")

		circ.info['hosts'] = consumed_res
		logging.debug(f"Circuit consumed: {consumed_res}")
		circ.assigned_qrc = self.qrc
		circ.assigned_qrc.increment_load()

	def free_resources(self, circ):
		res = circ.info['hosts']
		for host in res.keys():
			if host not in self.free_hosts:
				raise DEFwError(f"Circuit has untracked host: {host}")
			if res[host] + self.free_hosts[host] > MAX_PPN:
				raise DEFwError("Returning more resources than originally had")
			self.free_hosts[host] += res[host]
		if circ.assigned_qrc:
			circ.assigned_qrc.decrement_load()
		circ.set_done()
		cid = circ.get_cid()
		logging.debug(f"Deleting circuit {cid}")
		self.delete_circuit(cid)

	def common_run(self, cid):
		self.read_qrc_cqs()
		circuit = self.circuits[cid]
		self.consume_resources(circuit)
		logging.debug(f"Running {cid}\n{circuit.info}")
		return circuit

	def run_cmd(self, cmd):
		proc = Process(cmd, None, "")
		pid = proc.launch()
		procinfo = psutil.Process(pid)
		try:
			logging.debug(f"------{procinfo}")
			logging.debug(f"------{procinfo.ppid()}")
			logging.debug(f"------{procinfo.name()}")
			logging.debug(f"------{procinfo.exe()}")
			logging.debug(f"------{procinfo.cmdline()}")
			logging.debug(f"------{procinfo.cwd()}")
			logging.debug(f"------{procinfo.environ()}")
			logging.debug(f"------{procinfo.status()}")
			logging.debug(f"------{procinfo.create_time()}")
			logging.debug(f"------{procinfo.cpu_times()}")
			logging.debug(f"------{procinfo.connections()}")
			logging.debug(f"------{procinfo.threads()}")
			logging.debug(f"------{procinfo.children()}")
		except:
			pass
		stdout, stderr, rc = proc.get_result()
		proc.terminate()
		#rc = proc.run()
		return stdout, stderr, rc
		#return "out", "err", rc

	def test_sleep_app(self):
		cmd = "/sw/crusher/ums/ompix/DEVELOP/cce/13.0.0/install/openmpi-main-borg/bin/prterun -v --dvm file:/ccs/home/shehataa/QFwTmp/prte_dvm/dvm-uri -x LD_LIBRARY_PATH --report-bindings --display-map --display-allocation --pmixmca pmix_server_spawn_verbose 100 --pmixmca pmix_client_spawn_verbose 100 --np 1 /ccs/home/shehataa/mysleep.sh"
		#cmd = "/sw/frontier/ums/ums024/cce/15.0.0/install/openmpi-5.0.1-ompix-a4-20240320.debug/bin/mpirun --dvm file:/ccs/home/shehataa/QFwTmp/prte_dvm/dvm-uri -x LD_LIBRARY_PATH --report-bindings --display-map --display-allocation --np 1 /ccs/home/shehataa/mysleep.sh"
		#cmd = "/ccs/home/shehataa/mysleep.sh"
		for i in range(0, 3):
			logging.debug(f"run -- {cmd}")
			out, err, rc = self.run_cmd(cmd)
			logging.debug(f"\tout = {out}\n\terr = {err}\n\trc = {rc}")
		return f"This is a test return for command with rc: {rc}", rc

	def sync_run(self, cid):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = self.common_run(cid)
		try:
			rc, output = circuit.assigned_qrc.sync_run(cid, circuit.info)
		except Exception as e:
			self.free_resources(circuit)
			raise e
		self.free_resources(circuit)
		return rc, output
		#circ_result, stats = self.parse_result(output.decode('utf-8'))
		# TODO: Where is the best place to parse the results. Current
		# thinking would be in the QRC. The QRC is suppose to be
		# simulation specific backend
		#logging.debug(f"Circuit results = {circ_result}")
		#logging.debug(f"stats = {stats}")
		#return rc, circ_result, stats

	def async_run(self, cid):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = self.common_run(cid)

		try:
			circuit.assigned_qrc.async_run(cid, circuit.info)
		except Exception as e:
			self.free_resources(circuit)
			raise e

	def read_qrc_cqs(self):
		while (res := self.qrc.read_cq()):
			self.qrc.circuit_results.append(res)
			logging.debug(f"QRC has {len(self.qrc.circuit_results)} pending results")
			try:
				circ = self.circuits[res['cid']]
				self.free_resources(circ)
			except Exception as e:
				logging.debug(f"couldn't find cid: {res['cid']} in {self.circuits}")
				raise e

	def read_cq(self, cid=None):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		r = self.qrc.read_cq()

		if not r:
			if cid:
				raise DEFwInProgress(f"{cid} still in progress")
			else:
				raise DEFwInProgress("No ready QTs")

		return r

	def peek_cq(self, cid=None):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		r = self.qrc.peak_cq()

		if not r:
			if cid:
				raise DEFwInProgress(f"{cid} still in progress")
			else:
				raise DEFwInProgress("No ready QTs")

		return r

	def status(self, cid):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		return self.qrc.status(cid)

	def is_ready(self):
		if not common.qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		return True

	def query(self):
		from . import SERVICE_NAME, SERVICE_DESC
		from api_qpm import QPMType, QPMCapability
		from defw_agent_info import get_bit_list, get_bit_desc, \
									Capability, DEFwServiceInfo
		t = get_bit_list(QPMType.QPM_TYPE_SIMULATOR, QPMType)
		c = get_bit_list(QPMCapability.QPM_CAP_TENSORNETWORK, QPMCapability)
		cap = Capability(QPMType.QPM_TYPE_SIMULATOR,
						QPMCapability.QPM_CAP_TENSORNETWORK, get_bit_desc(t, c))
		info = DEFwServiceInfo(SERVICE_NAME, SERVICE_DESC,
							   self.__class__.__name__,
							   self.__class__.__module__,
							   cap, -1)
		return info

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services=None):
		if self.qrc:
			self.qrc.shutdown()
			self.qrc = None
		pass

	def schedule_shutdown(self, timeout=5):
		logging.debug(f"Shutting down in {timeout} seconds")
		time.sleep(timeout)
		me.exit()

	def shutdown(self):
		logging.debug("Scheduling QPM Shutdown")
		if self.qrc:
			self.qrc.shutdown()
			self.qrc = None
		ss = threading.Thread(target=self.schedule_shutdown, args=())
		ss.start()

	def test(self):
		return "****QPM Test Successful****"

