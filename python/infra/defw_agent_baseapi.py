from defw_remote import BaseRemote
from defw_util import prformat, fg, bg
import os, traceback, logging

class BaseAgentAPI(BaseRemote):
	def __init__(self, target=None, *args, **kwargs):
		super().__init__(target, *args, **kwargs)

	def query(self):
		# go over each of the service in each of the services module and
		# call their query function. If they don't have a query function
		# then they won't be picked up or advertised.
		#
		#traceback.print_stack()
		from defw import services
		for svc, module in services:
			if module.svc_info['name'] == 'Resource Manager':
				logging.debug("Can't query Resource Manager");
				return
			for c in module.service_classes:
				obj = c(start=False)
				return obj.query()

	'''
	reserve the svc passed in from the agent described by info
	'''
	def reserve(self, info, svc, client_ep, *args, **kwargs):
		from defw import services
		class_name = info.get_name()
		mod_name = info.get_module_name()
		if mod_name in services:
			mod = services[mod_name]
			for c in mod.service_classes:
				if class_name == c.__class__.__name__:
					obj = c()
					return obj.reserve(svc, client_ep, *args, **kwargs)

	def release(self, services):
		prformat(fg.bold+fg.lightgrey+bg.red, "Client doesn't implement RELEASE API")
		pass
