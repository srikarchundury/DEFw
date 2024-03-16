from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import os, subprocess, copy, yaml, logging, sys, threading
from time import sleep
from defw_exception import DEFwError, DEFwInProgress
sys.path.append(os.path.split(os.path.abspath(__file__))[0])
import launcher_common as common

class Process:
	def __init__(self, cmd, env, path):
		if path:
			self.__cmd = os.path.join(path, proc).split()
		else:
			self.__cmd = cmd.split()
		self.__pid = 0
		self.__process = None
		self.__appended_env = env
		self.__env = copy.deepcopy(dict(os.environ))
		if env and type(env) == dict:
			for k, v in env.items():
				self.__env[k] = v

	def launch(self, deamonize=False):
		cmd = " ".join(self.__cmd)
		logging.debug(f"Launch {cmd}:{deamonize} with env = \n--------\n{self.__appended_env}\n+++++++++")
		try:
			if deamonize:
				self.__process = subprocess.Popen(self.__cmd, env=self.__env,
								stdout=subprocess.PIPE, stderr=subprocess.PIPE,
								stdin=subprocess.PIPE, start_new_session=True)
			else:
				self.__process = subprocess.Popen(self.__cmd, env=self.__env,
								stdout=subprocess.PIPE, stderr=subprocess.PIPE,
								stdin=subprocess.PIPE, start_new_session=True)
			self.__pid = self.__process.pid
		except Exception as e:
			logging.critical(f"hit exception: {e}")
			raise e
		return self.__pid

	def get_result(self):
		output, error = self.__process.communicate()
		return output, error, self.__process.returncode

	def kill(self):
		logging.debug(f"Kill process with pid: {self.__pid}")
		self.__process.kill()
		try:
			os.waitpid(self.__pid, 0)
		except:
			pass

	def terminate(self):
		logging.debug(f"Terminate process with pid: {self.__pid}")
		self.__process.terminate()
		try:
			os.waitpid(self.__pid, 0)
		except:
			pass

	def poll(self):
		return self.__process.poll()

	def returncode(self):
		return self.__process.returncode

	def getpid(self):
		return self.__pid

class Launcher:
	def __init__(self, start=False):
		self.__proc_dict = {}
		self.__dead_procs = {}
		self.__monitor_thr = threading.Thread(target=self.monitor_thr)
		self.__monitor_thr.start()

	def monitor_thr(self):
		# TODO: If a process dies while it's doing work the user of the
		# process needs to detect that it's no longer there and abort
		# operations. Currently that'll rely on a timeout, which could be
		# pretty long
		while not common.shutdown:
			for pid, proc in self.__proc_dict.items():
				if proc.poll():
					logging.debug(f"{pid} died unexpectedly with rc {proc.returncode()}")
					proc.kill()
					self.__dead_procs[pid] = proc.returncode()
			for pid in self.__dead_procs.keys():
				if pid in self.__proc_dict.keys():
					del self.__proc_dict[pid]
			sleep(1)
		logging.debug("Monitor thread shutdown")

	def launch(self, cmd, env=None, path='', wait=False):
		proc = Process(cmd, env, path)
		# if we're going to wait for it keep it around until we get
		# the result
		proc.launch(deamonize=(not wait))
		self.__proc_dict[proc.getpid()] = proc
		pid = proc.getpid()
		if not wait:
			return pid
		output, error, rc = proc.get_result()
		if rc:
			proc.kill()
		del self.__proc_dict[pid]
		return output, error, rc

	def kill(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[pid].kill()
			del self.__proc_dict[pid]

	def terminate(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[pid].kill()
			del self.__proc_dict[pid]

	def status(self, pid):
		if pid in self.__dead_procs.key():
			rc = self.__dead_procs[pid]
			del self.__dead_procs[pid]
			return rc
		if pid in self.__proc_dic.keys():
			return 0
		raise DEFwInProgress(f"{pid} is still running")

	def shutdown(self, keep=False):
		rm_pid = []
		if not keep:
			for pid, proc in self.__proc_dict.items():
				proc.kill()
				rm_pid.append(pid)
			for pid in rm_pid:
				del self.__proc_dict[pid]
		logging.debug("Launcher Service shutdown requested")
		common.shutdown = True

	def query(self):
		from . import svc_info
		cap = Capability(svc_info['name'], svc_info['description'], 1)
		svc = ServiceDescr(svc_info['name'], svc_info['description'], [cap], 1)
		info = DEFwAgentInfo(self.__class__.__name__,
						  self.__class__.__module__, [svc])
		return info

	def test(self):
		logging.debug("Testing Launcher")

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services):
		self.runner_shutdown = True

