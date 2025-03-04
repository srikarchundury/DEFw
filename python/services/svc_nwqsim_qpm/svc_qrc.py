from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import logging, uuid, time, queue, threading, sys, os, io, contextlib
import importlib, yaml, psutil
from defw_exception import DEFwError, DEFwExists, DEFwExecutionError, DEFwInProgress, DEFwOutOfResources
import svc_launcher, cdefw_global
from defw_util import print_thread_stack_trace_to_logger

sys.path.append(os.path.split(os.path.abspath(__file__))[0])
import qpm_common as common

def dump_tmp_dir():
	try:
		for root, dirs, files in os.walk('/tmp'):
			logger.info(f"Directory: {root}")
			for file in files:
				logger.info(f"  File: {os.path.join(root, file)}")
	except:
		pass

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
	# number of worker threads started
	MAX_NUM_WORKERS = 8
	# max work queue size
	MAX_NUM_WORKER_TASKS = 256
	THREAD_STATE_FREE = 0
	THREAD_STATE_BUSY = 1

	def __init__(self, start=True):
		common.qpm_shutdown = False
		print_thread_stack_trace_to_logger(level='critical')
		logging.debug(f"NWQSIM_QRC INIT")
		self.circuit_results_lock = threading.Lock()
		self.worker_pool_lock = threading.Lock()
		self.circuit_results = []
		self.module_util = None
		self.colocated_dvm = False
		self.is_colocated_dvm()
		self.worker_pool = []
		self.worker_pool_rr = 0
		self.num_cores = psutil.cpu_count(logical=False)
		logging.debug(f'num_cores = {self.num_cores} start = {start}')
		if start:
			for x in range(0, QRC.MAX_NUM_WORKERS):
				with self.worker_pool_lock:
					runner = threading.Thread(target=self.runner, args=(x,))
					logging.debug(f"inserting {x} in the worker pool")
					self.worker_pool.append({'thread': runner,
										   'active_tasks': [],
										   'queue': queue.Queue(),
										   'state': QRC.THREAD_STATE_FREE})
					runner.daemon = True
					runner.start()

	def __del__(self):
		logging.critical(f"NWQSIM_QRC DEL")
		common.qpm_shutdown = True
		with self.worker_pool_lock:
			for v in self.worker_pool:
				v['queue'].put(None)

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

	def parse_result(self, out):
		try:
			out_str = out.decode("utf-8")
			if out_str == "":
				raise DEFwError({"Error": "Empty output!"})
				return {"Error": "Empty output!"}
			logging.debug(f"parse_result out_str = {out_str}")
			lines = out_str.split("\n")
			catch = -1
			for i, each_line in enumerate(lines):
				if "===============  Measurement" in each_line:
					catch = i
			if catch == -1:
				raise DEFwError({"Error": "Could not parse result!"})
				return {"Error": "Could not parse result!"}
			results = lines[catch+1:-1]
			counts = {}
			for each_res_line in results:
				k,v = each_res_line.split(":")
				k = k.strip('" ').strip()
				v = int(v)
				counts[k] = v
			return counts
		except Exception as e:
			raise DEFwError({"Error": str(e)})
			return {"Error": str(e)}

	def check_active_tasks(self, wid):
		complete = []
		for task_info in self.worker_pool[wid]['active_tasks']:
			logging.debug(f"check_active_tasks task_info is {task_info}")
			try:
				stdout, stderr, rc = task_info['launcher'].status(task_info['pid'])
				logging.debug(f"check_active_tasks stdout, stderr, rc = {stdout}, {stderr}, {rc}")
			except DEFwInProgress:
				logging.debug(f"{task_info} still in progress")
				continue
			except Exception as e:
				raise e

			# at this point, it already has a return code!
			logging.debug(f"{task_info} completed")
			complete.append(task_info)

			circ = task_info['circ']
			cid = circ.get_cid()
			qasm_file = task_info['qasm_file']

			if rc == 0:
				logging.debug(f"self.colocated_dvm = {self.colocated_dvm}")
				try:
					# TODO: process this output to return properly here.
					logging.debug(f"async stdout {stdout} ")
					output = self.parse_result(stdout)
					circ.set_exec_done()
				except Exception as e:
					logging.debug(f"exception = {e}")
					output = "{result: missing, exception: "+ f"{e}" + "}"
					circ.set_fail()
			else:
				stdout = stdout.decode('utf-8')
				stderr = stderr.decode('utf-8')
				res = stdout + '\n' + stderr
				output = "{result: "+ f"{res}" + "}"
				circ.set_fail()

			try:
				os.remove(qasm_file)
			except:
				pass

			r = {'cid': cid,
				 'result': output,
				 'rc': rc,
				 'launch_time': circ.launch_time,
				 'creation_time': circ.creation_time,
				 'exec_time': circ.exec_time,
				 'completion_time': circ.completion_time,
				 'resources_consumed_time': circ.resources_consumed_time,
				 'cq_enqueue_time': time.time(),
				 'cq_dequeue_time': -1 }

			logging.debug(f"Circuit {cid} successful with results {r}")
			circ.free_resources(circ)
			with self.circuit_results_lock:
				self.circuit_results.append(r)

		for task_info in complete:
			logging.debug(f" completed task_info = {task_info}")
			self.worker_pool[wid]['active_tasks'].remove(task_info)

	def runner(self, my_id):
		# get the next available entry on the queue
		# if one is available run it
		# check on currently running tasks to see if any of them complete
		# Add completed tasks to the results dictionary
		super_affinity = os.sched_getaffinity(0)
		with self.worker_pool_lock:
			my_queue = self.worker_pool[my_id]['queue']
			# bind to core
			# We can enhance this more to avoid core 0 in every l3 cache
			bound_core = (my_id + 1) % self.num_cores
			if not bound_core in super_affinity:
				tmp = bound_core + 1
				while tmp != bound_core:
					if tmp in super_affinity:
						bound_core = tmp
						break
					tmp  = (tmp + 1) % len(super_affinity)
			logging.debug(f'attempting to bind {threading.get_ident()} to ' \
					f'{bound_core} from  {os.sched_getaffinity(0)}')
			try:
				os.sched_setaffinity(0, {bound_core})
			except Exception as e:
				logging.critical(f'Failed to bind {threading.get_ident()} to {bound_core}')
				raise e

		logging.debug(f"starting QRC main loop for {my_id}: {common.qpm_shutdown}")

		while not common.qpm_shutdown:
			logging.debug(f"qrc_runner my_queue.qsize() = {my_queue.qsize()}")
			empty = False
			try:
				circ = my_queue.get(timeout = 0.001) # sleep
				if circ == None:
					common.qpm_shutdown = True
					continue
			except queue.Empty:
				empty = True

			self.check_active_tasks(my_id)

			if not empty:
				result = None
				pid = -1
				try:
					task_info = self.run_circuit_async(circ)
				except Exception as e:
					result = e
					rc = -1
					pass

				if my_queue.qsize() < QRC.MAX_NUM_WORKER_TASKS:
					with self.worker_pool_lock:
						self.worker_pool[my_id]['state'] = QRC.THREAD_STATE_FREE

				if result:
					r = {'cid': circ.get_cid(),
						'result': result,
						'rc': rc,
						'launch_time': circ.launch_time,
						'creation_time': circ.creation_time,
						'exec_time': circ.exec_time,
						'completion_time': circ.completion_time,
						'resources_consumed_time': circ.resources_consumed_time,
						'cq_enqueue_time': time.time(),
						'cq_dequeue_time': -1}
					logging.debug(f"Problem with circuit {cid} appending result {r}")
					with self.circuit_results_lock:
						self.circuit_results.append(r)
						circ.free_resources(circ)
						logging.debug(f"{len(self.circuit_results)} pending results")
				else:
					self.worker_pool[my_id]['active_tasks'].append(task_info)

	def read_cq(self, cid=None):
		if cid:
			with self.circuit_results_lock:
				logging.debug(f"read_cq for {cid}: {len(self.circuit_results)}")
				i = 0
				for e in self.circuit_results:
					if cid == e['cid']:
						r = self.circuit_results.pop(i)
						r['cq_dequeue_time'] = time.time()
						return r
					i += 1
		else:
			with self.circuit_results_lock:
				logging.debug(f"read_cq for top: {len(self.circuit_results)}")
				if len(self.circuit_results) > 0:
					r = self.circuit_results.pop(0)
					r['cq_dequeue_time'] = time.time()
					return r
		return None

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

		nwqsim_executable = shutil.which(info['qfw_backend'])
		gpuwrapper = shutil.which("gpuwrapper.sh")

		if not nwqsim_executable or not gpuwrapper:
			raise DEFwExecutionError("Couldn't find nwqsim_executable or gpuwrapper. Check paths")

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

		# Usage: ./nwq_qasm [options]
		# Option              Description
		# -q                  Executes a simulation with the given QASM file.
		# -qs                 Executes a simulation with the given QASM string.
		# -j                  Executes a simulation with the given json file with Qiskit Experiment Qobj.
		# -js                 Executes a simulation with the given json string.
		# -t <index>          Runs the testing benchmarks for the specific index provided.
		# -a                  Runs all testing benchmarks.
		# -backend_list       Lists all the available backends.
		# -metrics            Print the metrics of the circuit.
		# -backend <name>     Sets the backend for your program to the specified one (default: CPU). The backend name string is case-insensitive.
		# -shots <value>      Configures the total number of shots (default: 1024).
		# -sim <method>       Select the simulation method: sv (state vector, default), dm (density matrix). (default: sv).
		# -basis              Run the transpiled benchmark circuits which only contain basis gates.

		# cmd = f'{exec_cmd} --dvm {dvm} -x LD_LIBRARY_PATH ' \
		# 	  f'--mca btl ^tcp,ofi,vader,openib ' \
		# 	  f'--mca pml ^ucx --mca mtl ofi --mca opal_common_ofi_provider_include '\
		# 	  f'{info["provider"]} --map-by {info["mapping"]} --bind-to core '\
		# 	  f'--np {info["np"]} --host {hosts} {gpuwrapper} -v {nwqsim_executable} ' \
		# 	  f'-q {qasm_file} '

		# cmd = f'{exec_cmd} --dvm {dvm} -x LD_LIBRARY_PATH ' \
		# 	  f'--mca btl ^tcp,ofi,vader,openib ' \
		# 	  f'--mca pml ^ucx --mca mtl ofi --mca opal_common_ofi_provider_include '\
		# 	  f'{info["provider"]} --map-by {info["mapping"]} --bind-to core '\
		# 	  f'--np {info["np"]} --host {hosts} -v {nwqsim_executable} ' \
		# 	  f'-q {qasm_file} '

		cmd = f'{exec_cmd} --dvm {dvm} -x LD_LIBRARY_PATH ' \
			  f'--mca btl ^tcp,ofi,vader,openib ' \
			  f'--mca pml ^ucx --mca mtl ofi --mca opal_common_ofi_provider_include '\
			  f'{info["provider"]} --bind-to core '\
			  f'--np {info["np"]} --host {hosts} -v {nwqsim_executable} ' \
			  f'-q {qasm_file} '

		# cmd = f'{exec_cmd} --dvm {dvm} -x LD_LIBRARY_PATH ' \
		# 	f'--mca btl ^tcp,ofi,vader,openib ' \
		# 	f'--mca pml ^ucx --mca mtl ofi ' \
		# 	f'--mca mtl_ofi_max_send_size 8589934592 ' \
		# 	f'--mca mtl_ofi_max_recv_size 8589934592 ' \
		# 	f'--mca btl_sm_max_size 8589934592 ' \
		# 	f'--mca opal_common_ofi_provider_include {info["provider"]} ' \
		# 	f'--map-by {info["mapping"]} --bind-to core ' \
		# 	f'--np {info["np"]} --host {hosts} ' \
		# 	f'-v {nwqsim_executable} -q {qasm_file} '

		if "num_shots" in info:
			cmd += f' -shots {info["num_shots"]} '

		if "backend" in info:
			cmd += f'-backend {info["backend"]} '
		else:
			cmd += f'-backend MPI '

		if "method" in info:
			cmd += f' -sim {info["method"]}'

		logging.debug(f"NWQSim CMD - {cmd}")

		return cmd

	def run_circuit_async(self, circ):
		# check that we can run on CXI
		if "SLINGSHOT_VNIS" in os.environ:
			logging.debug(f"Found SLINGSHOT_VNIS: {os.environ['SLINGSHOT_VNIS']}")
		else:
			logging.debug(f"Didn't find SLINGSHOT_VNIS")

		cid = circ.get_cid()

		#self.load_modules(circ.info["modules"])

		tmp_dir = cdefw_global.get_defw_tmp_dir()

		qasm_c = circ.info["qasm"]
		qasm_file = os.path.join(tmp_dir, str(cid)+".qasm")
		logging.debug(f"Writing circuit file to {qasm_file}")
		with open(qasm_file, 'w') as f:
			f.write(qasm_c)

		circ.set_launching()
		launcher = svc_launcher.Launcher()
		logging.debug(f"Running Circuit NWQSIM --\n{qasm_c}")
		try:
			cmd = self.form_cmd(circ, qasm_file)

			task_info = {}
			pid = -1
			#env = {'FI_LOG_LEVEL': 'info'}
			#output, error, rc = launcher.launch(cmd, env=env, wait=True)
			#logging.critical(f"Running -- {cmd} -- with pid {pid}")
			pid = launcher.launch(cmd)
			circ.set_running()
		except Exception as e:
			os.remove(qasm_file)
			logging.critical(f"Failed to launch {cmd}")
			raise e

		task_info['circ'] = circ
		task_info['qasm_file'] = qasm_file
		task_info['launcher'] = launcher
		task_info['pid'] = pid

		logging.debug(f"NWQSIM task info - {task_info}")

		return task_info

	def run_circuit(self, circ):
		# check that we can run on CXI
		if "SLINGSHOT_VNIS" in os.environ:
			logging.debug(f"Found SLINGSHOT_VNIS: {os.environ['SLINGSHOT_VNIS']}")
		else:
			logging.debug(f"Didn't find SLINGSHOT_VNIS")

		#self.load_modules(circ.info["modules"])

		cid = circ.get_cid()

		tmp_dir = cdefw_global.get_defw_tmp_dir()

		qasm_c = circ.info["qasm"]
		qasm_file = os.path.join(tmp_dir, str(cid)+".qasm")
		logging.debug(f"Writing circuit file to {qasm_file}")
		with open(qasm_file, 'w') as f:
			f.write(qasm_c)

		circ.set_launching()
		launcher = svc_launcher.Launcher()
		logging.debug(f"Running Circuit --\n{qasm_c}")

		try:
			cmd = self.form_cmd(circ, qasm_file)
			logging.debug(f"Running -- {cmd}")
			circ.set_running()
			output, error, rc = launcher.launch(cmd, wait=True)
			output = self.parse_result(output)
			logging.debug(f"Completed -- {cmd} -- returned {rc} -- {output} -- {error}")
		except Exception as e:
			os.remove(qasm_file)
			logging.critical(f"Failed to launch {cmd}")
			raise e

		logging.debug(f"Removing {qasm_file}")
		os.remove(qasm_file)

		if rc == 0:
			logging.debug(f"Circuit {cid} successful")
			circ.set_exec_done()
			r = {'cid': cid,
				 'result': output,
				 'rc': rc,
				 'launch_time': circ.launch_time,
				 'creation_time': circ.creation_time,
				 'exec_time': circ.exec_time,
				 'completion_time': circ.completion_time,
				 'resources_consumed_time': circ.resources_consumed_time,
				 'cq_enqueue_time': time.time(),
				 'cq_dequeue_time': -1 }
			return r

		circ.set_fail()
		self.is_colocated_dvm()
		error_str = f"Circuit failed with {rc}:{output.decode('utf8')}:" \
				f"{error.decode('utf-8')}:dvm {self.colocated_dvm}:" \
				f"total run-time = {circ.exec_time - circ.completion_time}"
		logging.debug(error_str)
		raise DEFwExecutionError(error_str)

	def sync_run(self, circ):
		logging.debug(f"sync_run({circ.get_cid()}, {circ.info})")
		return self.run_circuit(circ)

	# Round robin over the workers so that they are all busy
	def async_run(self, circ):
		cid = circ.get_cid()
		rr = self.worker_pool_rr
		self.worker_pool_rr += 1
		idx = rr % QRC.MAX_NUM_WORKERS
		i = idx
		with self.worker_pool_lock:
			while True:
				worker = self.worker_pool[i]
				if worker['state'] == QRC.THREAD_STATE_FREE and \
				   worker['queue'].qsize() < QRC.MAX_NUM_WORKER_TASKS:
						worker['queue'].put(circ)
						if worker['queue'].qsize() >= QRC.MAX_NUM_WORKER_TASKS:
							worker['state'] = QRC.THREAD_STATE_BUSY
						return cid
				else:
					i = (i + 1) % QRC.MAX_NUM_WORKERS
					if i == idx:
						break
		# if we get here then there is no more threads to handle this
		# request. Raise an exception and the circuit will be queued
		raise DEFwOutOfResources(f"No more resource to run {cid}")

	def shutdown(self):
		logging.critical("shutdown called")
		common.qpm_shutdown = True

	def test(self):
		return "****Testing the NWQSIM QRC****"
