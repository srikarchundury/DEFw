from defw_exception import DEFwOutOfResources
from defw import me
import logging

# This is what an agent (either a service or a client) needs to return
# when queried about the services it offers:
# DEFwAgentInfo contains a list of ServiceDescr
# Each ServiceDescr has a list of Capability
# Each Capability describes a capacity it can handle
#
class Capability:
	def __init__(self, capability_name, capability_description, capacity):
		self.__capability_name = capability_name
		self.__capability_description = capability_description
		self.__capacity = capacity

	def __repr__(self):
		return f"Capbility(name={self.__capability_name}," \
				f" description={self.__capability_description}," \
				f" capacity={self.__capacity}"

	def get_capability_dict(self):
		return {'name': self.__capability_name,
				'description': self.__capability_description,
				'capacity': self.__capacity}

	def get_capability(self):
		return self

class ServiceDescr:
	def __init__(self, service_name, service_descr,
				 capabilities, max_capacity,
				 agent_descriptor=None):
		self.__service_name = service_name
		self.__service_descr = service_descr
		self.__capabilities = capabilities
		self.__agent_descriptor = agent_descriptor
		self.__max_capacity = max_capacity
		self.__cur_capacity = 0

	def __repr__(self):
		return f"Service(name={self.__service_name}," \
				f" description={self.__service_descr}," \
				f" capabilities={self.__capabilities}," \
				f" max capacity={self.__max_capacity}," \
				f" available capacity={self.__max_capacity - self.__cur_capacity}"

	def get_service_name(self):
		return self.__service_name

	def get_service_dict(self, Sfilter=None):
		if not Sfilter or Sfilter in self.__service_name:
			return {'name': self.__service_name,
					'description': self.__service_descr,
					'capabilities': self.__capabilities,
					'capacity': self.__max_reservation,
					'Owning Agent': self.__agent_descriptor}

	def get_service(self, Sfilter=None):
		if not Sfilter or Sfilter in self.__service_name:
			return self

	def consume_capacity(self):
		if self.__cur_capacity == self.__max_capacity:
			raise FIWOutOfResources(f"Exceeded capacity on {self.__service_name}")
		self.__cur_capacity += 1

	def release_capacity(self):
		if self.__cur_capacity == 0:
			raise FIWOutOfResources(f"Release unreserved service {self.__service_name}")
		self.__cur_capacity += 1

class DEFwAgentInfo:
	def __init__(self, name, mname, services):
		self.__name = name
		self.__module_name = mname
		self.__my_ep = me.my_endpoint()
		self.__owned_services = services

	def __contains__(self, item):
		for svc in self.__owned_services:
			if svc.get_service_name() == item.get_service_name():
				return True
		return False

	def get_services(self, Sfilter=None):
		if not Sfilter:
			return self.__owned_services

		viable_services = []
		for s in self.__owned_services:
			logging.debug(f"get_services({s}, {Sfilter})")
			if s.get_service(Sfilter):
				viable_services.append(s)

		return viable_services

	def get_name(self):
		return self.__name

	def get_module_name(self):
		return self.__module_name

	def get_endpoint(self):
		return self.__my_ep

	def __repr__(self):
		return f"Agent Info(name={self.__name}, Residence={self.__my_ep}, Services Owned={self.__owned_services}"


