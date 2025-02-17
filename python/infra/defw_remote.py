import defw_agent
import cdefw_global
from defw_exception import DEFwError, DEFwAgentNotFound
from defw_common_def import load_pref
from defw import me, get_agent, dump_all_agents
import uuid, logging

class BaseRemote(object):
	# the idea of the *args and **kwargs in the __init__ method is for subclasses
	# to pass all their arguments to the super() class. Then the superclass can then pass
	# that to the remote, so the remote class can be instantiated appropriately
	def __init__(self, service_info=None, blocking=True, target=None, *args, **kwargs):
		# if a target is specified other than me then we're going
		# to execute on that target
		self.__blocking = blocking
		if service_info:
			try:
				target = service_info.get_endpoint()
				self.__agent = get_agent(target)
			except Exception as e:
				print(e)
				raise DEFwError("Unknown Agent for service_info: ", service_info)
			self.__remote = True
		elif target:
			try:
				self.__agent = get_agent(target)
			except Exception as e:
				print(e)
				raise DEFwError("Unknown Agent: ", target)
			self.__remote = True
		else:
			self.__remote = False
			return

		if not self.__agent:
			print(f"agent not found {target}. Dumping all agents")
			dump_all_agents()
			print("End of agent dump")
			raise DEFwAgentNotFound(f"agent not found {target}")

		if service_info:
			self.__service_module = service_info.get_module_name()
		elif target:
			self.__service_module = type(self).__module__

		self.__class_id = str(uuid.uuid1())
		self.__agent.send_req('instantiate_class', me.my_endpoint(),
				self.__service_module,
				type(self).__name__, '__init__',
				self.__class_id, self.__blocking, *args, **kwargs)

	def __getattribute__(self, name):
		attr = object.__getattribute__(self, name)
		if hasattr(attr, '__call__'):
			def newfunc(*args, **kwargs):
				if self.__remote:
					# execute on the remote defined by:
					#     self.target
					#     attr.__name__ = name of method
					#     type(self).__name__ = name of class
					result = self.__agent.send_req('method_call',
								me.my_endpoint(),
								self.__service_module,
								type(self).__name__,
								attr.__name__,
								self.__class_id,
								self.__blocking,
								*args, **kwargs)
				else:
					result = attr(*args, **kwargs)
				return result
			return newfunc
		else:
			return attr

	def __del__(self):
		try:
			# signal to the remote that the class is being destroyed
			if self.__remote:
				self.__agent.send_req('destroy_class', me.my_endpoint(),
					self.__class__.__module__, type(self).__name__, '__del__',
					self.__class_id)
		except:
			pass

def defwrc(error, *args, **kwargs):
	rc = {}
	if error == -1:
		rc['status'] = 'FAIL'
	elif error == -2:
		rc['status'] = 'SKIP'
	else:
		rc['status'] = 'PASS'
	if len(args):
		rc['args'] = list(args)
	if len(kwargs):
		rc['kwargs'] = kwargs
	return rc


