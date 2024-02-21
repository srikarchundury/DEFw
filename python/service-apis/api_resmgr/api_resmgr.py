from defw_baseicpa import BaseRemote

"""
Interface module for the Resource Manager
"""

class IResMgr(BaseRemote):
	def __init__(self, ep):
		super().__init__(target=ep)

	"""
	Register a client with the Resource Manager

	Args:
		client_ep (endpoint): Client endpoint

	Returns:
		None

	Raises:
		IFWCommError: If Resource Manager is not reachable
	"""
	def register_client(self, client_ep):
		pass

	"""
	Register a service with the Resource Manager

	Args:
		client_ep (endpoint): service endpoint

	Returns:
		agent: An agent class instance which references the service

	Raises:
		IFWCommError: If Resource Manager is not reachable
	"""
	def register_service(self, service_ep):
		pass

	"""
	De-register an agent

	Args:
		agent (Agent): Agent instance to deregister

	Returns:
		None

	Raises:
		IFWCommError: If Resource Manager is not reachable
		IFWAgentNotFound: If agent is not registered
	"""
	def deregister(self, agent_ep):
		pass

	"""
	List all available Agents in the Intersect Network

	Args:
		service_filter: a string to filter services on

	Returns:
		dict: dictionary of services available on each agent

	Raises:
		IFWCommError: If Resource Manager is not reachable
	"""
	def get_services(self, service_filter=None):
		pass

	"""
	Reserve an Agent which exists on the Intersect Network

	Args:
		servics (dict): Dictionary of services to reserve

	Returns:
		None

	Raises:
		IFWCommError: If Resource Manager is not reachable
		IFWReserveError: If there is an error in the reservation process
	"""
	def reserve(self, services):
		pass

	"""
	Release a reserved Agent

	Args:
		servics (dict): Dictionary of services to release

	Returns:
		None

	Raises:
		IFWCommError: If Resource Manager is not reachable
		IFWReserveError: If there is an error in the release process
	"""
	def release(self, agents):
		pass



