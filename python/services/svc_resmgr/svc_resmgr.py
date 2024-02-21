"""
Interface module for the Resource Manager
"""
from defw_agent import Endpoint
from defw import me, active_service_agents, active_client_agents, \
					service_agents, client_agents
from defw_agent_baseapi import BaseAgentAPI
from defw_exception import IFWError,IFWCommError,IFWAgentNotFound,\
						  IFWInternalError,IFWRemoteError,IFWReserveError
from defw_util import prformat, fg, bg
import logging, uuid

# Agent states

# Agent has connected but not registered
AGENT_STATE_CONNECTED = 1 << 0
# Agent connected and registered
AGENT_STATE_REGISTERED = 1 << 1
# Agent connected has registered previously but now has unregistered
AGENT_STATE_UNREGISTERED = 1 << 2
# Agent is in error state
AGENT_STATE_ERROR = 1 << 3

class IResMgr:
	SVC = 'services'
	ACTV_SVC = 'active services'
	CLT = 'clients'
	ACTV_CLT = 'active clients'
	def __init__(self):
		self.__services_db = {}
		self.__clients_db = {}
		self.__active_services_db = {}
		self.__active_clients_db = {}
		self.__dbs = {IResMgr.SVC: self.__services_db,
					  IResMgr.ACTV_SVC: self.__active_services_db,
					  IResMgr.CLT: self.__clients_db,
					  IResMgr.ACTV_CLT: self.__active_clients_db}
		self.__my_ep = me.my_endpoint()
		self.__reload_resources()

	def __grab_agent_info(self, agent_dict, db, skip_self=False):
		agent_dict.reload()
		for k, agent in agent_dict.items():
			ep = agent.get_ep()
			if ep == self.__my_ep and skip_self:
				continue
			client_api = BaseAgentAPI(target=ep)
			aname = agent.get_name()
			db[aname] = \
				{'agent': agent,
				 'api': client_api,
				 'info': client_api.query()}
			if not 'state' in db[aname]:
				db[aname]['state'] = AGENT_STATE_CONNECTED

	def __reload_resources(self):
		self.__grab_agent_info(client_agents, self.__clients_db)
		# TODO: I'm disabling the resmgr trying to query itself for now.
		# Figure out how to properly handle this
		#
		self.__grab_agent_info(active_client_agents, self.__active_clients_db)
		self.__grab_agent_info(service_agents, self.__services_db, skip_self=True)
		self.__grab_agent_info(active_service_agents, self.__active_services_db, skip_self=True)

	def __register(self, global_agent_dict, agent_dict, ep):
		agent_dict.reload()
		agent = get_spec_agent(ep, global_agent_dict)
		if not agent:
			if ep.name in agent_dict:
				agent_dict[ep.name]['state'] = \
					agent_dict[ep.name]['state'] | AGENT_STATE_ERROR
			IFWAgentNotFound(f"Registeration from an unknown client {ep.name}")
		self.__grab_agent_info({agent.get_name(): agent},
				agent_dict, skep_self=True)
		agent_dict[agent.get_name()]['state'] = \
			agent_dict[agent.get_name()]['state'] | AGENT_STATE_REGISTERED
		return

	"""
	Register a client with the Resource Manager

	Args:
		client_ep (endpoint): Client endpoint

	Returns:
		None

	Raises:
		IFWCommError: If Resource Manager is not reachable
	"""
	def register_client(self, ep):
		self.__register(client_agents, self.__clients_db, ep)

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
		self.__register(service_agents, self.__services_db, ep)

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
	def deregister(self, ep):
		if ep.name not in self.__clients_db and \
		   ep.name not in self.__services_db:
			   raise IFWAgentNotFound(f"agent {ep.name} not found")
		if ep.name in self__services_db:
			self.__services_db[ep.name]['api'].unregister()
			del self.__services_db[ep.name]
		else:
			self.__clients_db[ep.name]['api'].unregister()
			del self.__clients_db[ep.name]
		return

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
		services = {}
		self.__reload_resources()
		for k, v in self.__active_services_db.items():
			if not v['info']:
				continue
			s =  v['info'].get_services(service_filter)
			if len(s) > 0:
				services[k] = {'loc': IResMgr.ACTV_SVC, 'services': s,
							   'api': v['info'].get_name()}
		for k, v in self.__services_db.items():
			if not v['info']:
				continue
			s =  v['info'].get_services(service_filter)
			if len(s) > 0:
				services[k] = {'loc': IResMgr.SVC, 'services': s,
							   'api': v['info'].get_name()}
		return services

	"""
	Reserve an Agent which exists on the Intersect Network

	Args:
		servics (dict): Dictionary of services to reserve

	Returns:
		endpoint list of all services reserved

	Raises:
		IFWCommError: If Resource Manager is not reachable
		IFWReserveError: If there is an error in the reservation process
	"""
	def reserve(self, client_ep, services, *args, **kwargs):
		svc_eps = []
		for k, v in services.items():
			db = self.__dbs[v['loc']]
			if not db[k]['state'] & AGENT_STATE_REGISTERED:
				IFWReserveError(f"Agent {k} is not registered")
			for s in v['services']:
				s.consume_capacity()
			logging.debug(f"reserve - {k}, {v}")
			api = db[k]['api']
			try:
				api.reserve(db[k]['info'], v['services'], client_ep, *args, **kwargs)
			except Exception as e:
				raise IFWReserveError(str(e))
			ep = db[k]['agent'].get_ep()
			# if this is a remote endpoint we should NULL out the blk_uuid
			# because it wouldn't mean anything here.
			if ep.remote_uuid != me.my_uuid():
				ep.blk_uuid = str(uuid.UUID(int=0))
			svc_eps.append(db[k]['agent'].get_ep())
		return svc_eps


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
	def release(self, services):
		for k, v in services.items():
			if not self.__services_db[k]['state'] & AGENT_STATE_REGISTERED:
				IFWReserveError(f"Agent {f} is not registered")
			for s in v['services']:
				s.release_capacity()
			logging.debug(f"release - {k}, {v}")
			api = self.__services_db[k]['api']
			try:
				api.release()
			except Exception as e:
				raise IFWReserveError(str(e))

	def query(self):
		prformat(fg.bold+fg.lightgrey+bg.red, "Resmgr doesn't implement QUERY API")
		pass

