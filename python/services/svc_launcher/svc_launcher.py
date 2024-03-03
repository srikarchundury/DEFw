from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import os, subprocess, copy, yaml
from defw_exception import DEFwError

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
		print(self.__cmd)
		print(yaml.dump(self.__env))

		self.__process = subprocess.Popen(self.__cmd, env=self.__env,
						stdout=subprocess.DEVNULL , stderr=subprocess.DEVNULL,
						stdin=subprocess.PIPE, start_new_session=True)
		self.__pid = self.__process.pid
		return self.__pid

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
		print(f"killing {pid} {self.__proc_dict.keys()}")
		if pid in self.__proc_dict.keys():
			print(f"killing {pid}")
			self.__proc_dict[pid].kill()
			print(f"removing {pid}")
			del self.__proc_dict[pid]
		print(f"killed {pid}")

	def terminate(self, pid):
		if pid in self.__proc_dict.keys():
			self.__proc_dict[pid].kill()
			del self.__proc_dict[proc.getpid()]

	def shutdown(self):
		for pid, proc in self.__proc_dict:
			del self.__proc_dict[proc.getpid()]
			proc.kill()

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

