import defw_agent
import cdefw_global
from defw_exception import IFWError
from defw_common_def import load_pref
from defw import me, get_agent
import uuid

class BaseRemote(object):
	# the idea of the *args and **kwargs in the __init__ method is for subclasses
	# to pass all their arguments to the super() class. Then the superclass can then pass
	# that to the remote, so the remote class can be instantiated appropriately
	def __init__(self, target=None, blocking=True, *args, **kwargs):
		# if a target is specified other than me then we're going
		# to execute on that target
		if target:
			try:
				self.__agent = get_agent(target)
			except:
				raise IFWError("Unknown Agent: ", target)
			self.__remote = True
			self.__blocking = blocking
		else:
			self.__remote = False
			return

		# We're going to have to handle a special case with service-apis.
		# The module name for these calls are going to be something like:
		#	service-apis.suite_qhpc.api_qhpc
		# however, we don't want that we want:
		#	services.suite_qhpc.svc_qhpc
		# TODO: There ought to be a better way to do this but for now
		# we'll just parse out the 'dot' notation and do the appropriate
		# massaging
		#
		module = type(self).__module__
		split = module.split('.')
		new_module_comp = []
		for s in split:
			if s == 'service-apis':
				new_module_comp.append('services')
			elif 'api_' in s:
				ns = 'svc_'+s.split('api_')[1]
				new_module_comp.append(ns)
			else:
				new_module_comp.append(s)
		new_module = '.'.join(new_module_comp)

		self.__service_module = new_module

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


