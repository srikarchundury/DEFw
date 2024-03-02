from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import os, subprocess
from defw_exception import DEFwError

class Process:
	def __init__(self, cmd, env, path):
		if path:
			self.__cmd = os.path.join(path, proc)
		else:
			self.__cmd = cmd
		self.__pid = 0
		self.__process = None
		self.__env = env

	def launch(self):
		self.__process = subprocess.Popen(self.__cmd, env=self.__env, shell=True)
		self.__proc = self.__process.pid

	def kill(self):
		self.__process.kill()

	def terminate(self):
		self.__process.terminate()

	def getpid(self):
		return self.__pid

class Launcher:
	def __init__(self, start=False):
		self.__proc_dict = {}

	def launch(self, proc, env=None, path=''):
		proc = Process(proc, env, path)
		proc.launch()
		self.__proc_dict[proc.getpid()] = proc
		return proc.getpid()

	def kill(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[proc.getpid()].kill()
			del self.__proc_dict[proc.getpid()]

	def terminate(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[proc.getpid()].kill()
			del self.__proc_dict[proc.getpid()]

	def shutdown(self):
		for pid, proc in self.__proc_dict:
			proc.kill()
			del self.__proc_dict[proc.getpid()]

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

