from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import logging, uuid, time, queue, threading, sys, os, io, contextlib
import importlib
from defw_exception import DEFwError, DEFwExists, DEFwExecutionError
import svc_launcher, cdefw_global

CID_COUNTER = 0
QCR_VERBOSE = 1

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
	def __init__(self, start=True):
		self.circuits = {}
		self.runner_queue = queue.Queue()
		self.circuit_results = []
		self.runner_shutdown = False
		self.module_util = None
		self.colocated_dvm = False
		self.is_colocated_dvm()
		if start:
			self.runner = threading.Thread(target=self.runner, args=())
			self.runner.start()

	def __del__(self):
		self.runner_shutdown = True
		self.runner_queue.put(-1)

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

	def runner(self):
		logging.debug(f"starting QRC main loop: {sys.path}")
		while not self.runner_shutdown:
			try:
				cid = self.runner_queue.get(timeout=1)
				if cid == -1:
					self.runner_shutdown = True
					continue
			except queue.Empty:
				continue
			exception = None
			try:
				rc, result = self.run_circuit(cid)
			except Exception as e:
				exception = e
				pass
			if exception:
				rc = e
			r = {'cid': cid, 'result': result, 'rc': rc}
			self.circuit_results.append(r)

	def read_cq(self, cid=None):
		if cid:
			i = 0
			for e in self.circuit_results:
				if cid == e['cid']:
					r = self.circuit.pop(i)
					return r
				i += 1
		else:
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

		# TODO: we need to provide a DVM URI
		#
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

		hosts = ",".join(f"{node}:*" for node in info["hosts"])

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
			  f'--np {info["np"]} --host {hosts} {gpuwrapper} {circuit_runner} ' \
			  f'-q {qasm_file} -b {info["num_qubits"]} -s {info["num_shots"]} ' \
			  f'-c {compiler}'

		return cmd

	def run_circuit(self, cid):
		circ = self.circuits[cid]

		#self.load_modules(circ.info["modules"])

		tmp_dir = cdefw_global.get_defw_tmp_dir()

		qasm_c = circ.info["qasm"]
		logging.debug(f"Writing circuit file to {tmp_dir}")
		qasm_file = os.path.join(tmp_dir, str(cid)+".qasm")
		with open(qasm_file, 'w') as f:
			f.write(qasm_c)

		retries = 0
		circ.set_running()
		launcher = svc_launcher.Launcher()
		while True:
			logging.debug(f"Running Circuit\n{qasm_c}")
			cmd = self.form_cmd(circ, qasm_file)
			logging.debug(f"Running {cmd}")

			try:
				output, error, rc = launcher.launch(cmd, wait=True)
				break
			except Exception as e:
				if retries < 3:
					# I'm trying to handle the case where the DVM might
					# not have started yet
					self.is_colocated_dvm()
					time.sleep(1)
					retries += 1
					continue
				os.remove(qasm_file)
				logging.critical(f"Failed to launch {cmd}")
				raise e

		os.remove(qasm_file)

		if not rc:
			circ.set_done()
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
		self.runner_queue.put(cid)
		return cid

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
