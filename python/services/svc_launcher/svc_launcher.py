from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import os, subprocess, copy, yaml, logging, sys, threading
from time import sleep
from defw_exception import DEFwError
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
		self.__env = copy.deepcopy(dict(os.environ))
		for k, v in env.items():
			self.__env[k] = v

	def launch(self):
		cmd = " ".join(self.__cmd)
		logging.debug(f"Launch {cmd}")
		self.__process = subprocess.Popen(self.__cmd, env=self.__env,
						stdout=subprocess.DEVNULL , stderr=subprocess.DEVNULL,
						stdin=subprocess.PIPE, start_new_session=True)
		self.__pid = self.__process.pid
		return self.__pid

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
		self.__monitor_thr = threading.Thread(target=self.monitor_thr)
		self.__monitor_thr.start()

	def monitor_thr(self):
		# TODO: If a process dies while it's doing work the user of the
		# process needs to detect that it's no longer there and abort
		# operations. Currently that'll rely on a timeout, which could be
		# pretty long
		while not common.shutdown:
			rm_pid = []
			for pid, proc in self.__proc_dict.items():
				if proc.poll():
					logging.debug(f"{pid} died unexpectedly with rc {proc.returncode()}")
					proc.kill()
					rm_pid.append(pid)
			for pid in rm_pid:
				del self.__proc_dict[pid]
			sleep(1)

	def launch(self, proc, env=None, path=''):
		proc = Process(proc, env, path)
		proc.launch()
		self.__proc_dict[proc.getpid()] = proc
		return proc.getpid()

	def kill(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[pid].kill()
			del self.__proc_dict[pid]

	def terminate(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[pid].kill()
			del self.__proc_dict[pid]

	def shutdown(self):
		rm_pid = []
		for pid, proc in self.__proc_dict:
			proc.kill()
			rm_pid.append(pid)
		for pid in rm_pid:
			del self.__proc_dict[pid]

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

