from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import logging, uuid, time, queue, threading, sys, os, io, contextlib
import importlib, yaml
from defw_exception import DEFwError, DEFwExists, DEFwExecutionError
import svc_launcher, cdefw_global

CID_COUNTER = 0
QCR_VERBOSE = 1

def dump_tmp_dir():
	try:
		for root, dirs, files in os.walk('/tmp'):
			logger.info(f"Directory: {root}")
			for file in files:
				logger.info(f"  File: {os.path.join(root, file)}")
	except:
		pass

class CircuitStates:
	UNDEF = 0
	READY = 1
	RUNNING = 2
	DONE = 3
	FAIL = 4

class Circuit:
	def __init__(self, cid, info):
		self.__state = CircuitStates.UNDEF
		self.info = info
		self.cid = cid

	def getState(self):
		return self.__state

	def setState(self, state):
		# State is monotonically increasing
		if self.__state > state:
			return False
		self.__state = state
		return True

	def set_ready(self):
		return self.setState(CircuitStates.READY)

	def set_running(self):
		return self.setState(CircuitStates.RUNNING)

	def set_done(self):
		return self.setState(CircuitStates.DONE)

	def set_fail(self):
		return self.setState(CircuitStates.FAIL)

	def status(self):
		if self.__state == CircuitStates.READY:
			return 'READY'
		if self.__state == CircuitStates.RUNNING:
			return 'RUNNING'
		if self.__state == CircuitStates.DONE:
			return 'DONE'
		if self.__state == CircuitStates.FAIL:
			return 'FAIL'

		return 'BUG'

@contextlib.contextmanager
def suppress_prints():
	# Save the original stdout
	original_stdout = sys.stdout
	original_stderr = sys.stderr
	sys.stdout = io.StringIO()
	sys.stderr = io.StringIO()

	yield

	sys.stdout = original_stdout
	sys.stderr = original_stderr

class QRC:
	MAX_NUM_WORKERS = 8
	THREAD_STATE_FREE = 0
	THREAD_STATE_BUSY = 1

	def __init__(self, start=True):
		self.circuits = {}
		self.circuit_results_lock = threading.Lock()
		self.worker_pool_lock = threading.Lock()
		self.circuit_results = []
		self.runner_shutdown = False
		self.module_util = None
		self.colocated_dvm = False
		self.is_colocated_dvm()
		self.worker_pool = {}
		if start:
			for x in range(0, QRC.MAX_NUM_WORKERS):
				with self.worker_pool_lock:
					runner = threading.Thread(target=self.runner, args=(x,))
					logging.debug(f"inserting {x} in the worker pool")
					self.worker_pool[x] = {'thread': runner,
										   'queue': queue.Queue(),
										   'state': QRC.THREAD_STATE_FREE}
					runner.start()

	def __del__(self):
		self.runner_shutdown = True
		with self.worker_pool_lock:
			for k, v in self.worker_pool.items():
				v['queue'].put(-1)

	def is_colocated_dvm(self):
		import psutil
		pids = psutil.pids()
		for pid in pids:
			try:
				proc = psutil.Process(pid)
				if "prte" == proc.name():
					logging.debug(f"Found prte: {proc}")
					self.colocated_dvm = True
					return
			except:
				continue

	def runner(self, my_id):
		with self.worker_pool_lock:
			if my_id not in self.worker_pool:
				logging.debug(f"{my_id}: A worker thread is not part of the pool")
			my_queue = self.worker_pool[my_id]['queue']
		logging.debug(f"starting QRC main loop for {my_id}")
		while not self.runner_shutdown:
			try:
				cid = my_queue.get(timeout=1)
				if cid == -1:
					self.runner_shutdown = True
					continue
			except queue.Empty:
				continue
			exception = None
			try:
				rc, result = self.run_circuit(cid)
			except Exception as e:
				result = e
				rc = -1
				pass
			with self.worker_pool_lock:
				self.worker_pool[my_id]['state'] = QRC.THREAD_STATE_FREE
			r = {'cid': cid, 'result': result, 'rc': rc}
			logging.debug(f"Circuit {cid} completed with result {r}")
			with self.circuit_results_lock:
				self.circuit_results.append(r)
				logging.debug(f"{len(self.circuit_results)} pending results")

	def read_cq(self, cid=None):
		if cid:
			with self.circuit_results_lock:
				logging.debug(f"read_cq for {cid}: {len(self.circuit_results)}")
				i = 0
				for e in self.circuit_results:
					if cid == e['cid']:
						r = self.circuit.pop(i)
						return r
					i += 1
		else:
			with self.circuit_results_lock:
				logging.debug(f"read_cq for top: {len(self.circuit_results)}")
				if len(self.circuit_results) > 0:
					r = self.circuit_results.pop(0)
					return r
		return None

	def create_circuit(self, cid, info):
		if cid not in self.circuits.keys():
			self.circuits[cid] = Circuit(cid, info)
		else:
			raise DEFwExists(f"{cid} already exists")

	def import_module_util(self):
		try:
			mod_path = os.path.join(os.environ['MODULESHOME'], "init",
					"env_modules_python.py")
			mod_name = "env_modules_python"
			spec = importlib.util.spec_from_file_location(mod_name,
					mod_path)
			self.module_util = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(self.module_util)
		except:
			raise DEFwError("module utility not available on this system")

	def load_modules(self, modules):
		if not self.module_util:
			self.import_module_util()

		for use in modules['use']:
			self.module_util.module("use", use)
		for mod in modules['mods']:
			self.module_util.module("load", mod)

		with suppress_prints():
			mod_list = self.module_util.module("list")
		logging.debug(f"Module loaded\n{mod_list[1]}")

	def form_cmd(self, circ, qasm_file):
		import shutil

		info = circ.info

		if 'compiler' not in info:
			compiler = 'staq'
		else:
			compiler = info['compiler']

		circuit_runner = shutil.which(info['qfw_circuit_runner_path'])
		gpuwrapper = shutil.which("gpuwrapper.sh")

		if not circuit_runner or not gpuwrapper:
			raise DEFwExecutionError("Couldn't find circuit_runner or gpuwrapper. Check paths")

		if not os.path.exists(info["qfw_dvm_uri_path"].split('file:')[1]):
			raise DEFwExecutionError(f"dvm-uri {info['qfw_dvm_uri_path']} doesn't exist")

		hosts = ''
		for k, v in info["hosts"].items():
			if hosts:
				hosts += ','
			hosts += f"{k}:{v}"

		dump_tmp_dir()
		if self.colocated_dvm:
			dvm = info["qfw_dvm_uri_path"]
		else:
			dvm = "search"

		exec_cmd = shutil.which(info["exec"])
		#exec_cmd = info["exec"]

#		cmd = f'{circuit_runner} ' \
#			  f'-q {qasm_file} -b {info["num_qubits"]} -s {info["num_shots"]} ' \
#			  f'-c {compiler} -v'
		cmd = f'{exec_cmd} --dvm {dvm} -x LD_LIBRARY_PATH ' \
			  f'--mca btl ^tcp,ofi,vader,openib ' \
			  f'--mca pml ^ucx --mca mtl ofi --mca opal_common_ofi_provider_include '\
			  f'{info["provider"]} --map-by {info["mapping"]} --bind-to core '\
			  f'--np {info["np"]} --host {hosts} {gpuwrapper} -v {circuit_runner} ' \
			  f'-q {qasm_file} -b {info["num_qubits"]} -s {info["num_shots"]} ' \
			  f'-c {compiler}'
#			  f'-c {compiler} 2>&1 | tee {output_file}'

		return cmd

	def run_circuit(self, cid):
		# check that we can run on CXI
		if "SLINGSHOT_VNIS" in os.environ:
			logging.debug(f"Found SLINGSHOT_VNIS: {os.environ['SLINGSHOT_VNIS']}")
		else:
			logging.critical(f"Didn't find SLINGSHOT_VNIS")

		circ = self.circuits[cid]

		#self.load_modules(circ.info["modules"])

		tmp_dir = cdefw_global.get_defw_tmp_dir()

		qasm_c = circ.info["qasm"]
		qasm_file = os.path.join(tmp_dir, str(cid)+".qasm")
		logging.debug(f"Writing circuit file to {qasm_file}")
		with open(qasm_file, 'w') as f:
			f.write(qasm_c)

		retries = 0
		circ.set_running()
		launcher = svc_launcher.Launcher()
		logging.debug(f"Running Circuit --\n{qasm_c}")
		cmd = self.form_cmd(circ, qasm_file)
		logging.debug(f"Running -- {cmd}")

		try:
			env = {'FI_LOG_LEVEL': 'info'}
			output, error, rc = launcher.launch(cmd, env=env, wait=True)
			logging.debug(f"COMMAND returned {rc}")
		except Exception as e:
			os.remove(qasm_file)
			logging.critical(f"Failed to launch {cmd}")
			raise e

		logging.debug(f"Removing {qasm_file}")
		os.remove(qasm_file)

		if not rc:
			logging.debug(f"Circuit {cid} successful")
			try:
				output_file = qasm_file+".result.r0"
				with open(output_file, 'r') as f:
					output = f.read()
					output = yaml.safe_load(output)
				os.remove(output_file)
				circ.set_done()
			except Exception as e:
				output = "{result: missing, exception: "+ f"{e}"
			return 0, output
		circ.set_fail()
		self.is_colocated_dvm()
		error_str = f"Circuit failed with {rc}:{output.decode('utf8')}:" \
				f"{error.decode('utf-8')}:dvm {self.colocated_dvm}"
		logging.debug(error_str)
		raise DEFwExecutionError(error_str)

	def sync_run(self, cid, info):
		self.create_circuit(cid, info)
		return self.run_circuit(cid)

	def async_run(self, cid, info):
		self.create_circuit(cid, info)
		with self.worker_pool_lock:
			for k, v in self.worker_pool.items():
				if v['state'] == QRC.THREAD_STATE_FREE:
					v['state'] = QRC.THREAD_STATE_BUSY
					v['queue'].put(cid)
					return cid
		#TODO: find the one with the shortest queue
		self.worker_pool[0]['queue'].put(cid)

	def query(self):
		from . import svc_info
		cap = Capability(svc_info['name'], svc_info['description'], 1)
		svc = ServiceDescr(svc_info['name'], svc_info['description'], [cap], 1)
		info = DEFwAgentInfo(self.__class__.__name__,
						  self.__class__.__module__, [svc])
		return info

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services):
		self.runner_shutdown = True

	def test(self):
		return "****Testing the QRC****"
