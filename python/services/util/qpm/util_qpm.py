from defw_agent_info import *
from defw_util import expand_host_list, round_half_up, round_to_nearest_power_of_two
from defw import me
import logging, uuid, time, queue, threading, logging, yaml
from defw_exception import DEFwError, DEFwNotReady, DEFwInProgress
import os
from .util_circuit import Circuit, MAX_PPN

qpm_initialized = False
qpm_shutdown = False

class UTIL_QPM:
	def __init__(self, qrc, max_ppn=MAX_PPN, start=True):
		self.circuits = {}
		#self.runner_queue = queue.Queue()
		self.oor_queue = queue.Queue()
		self.circuit_results = []
		self.qrc = qrc
		self.free_hosts = {}
		self.max_ppn = max_ppn
		self.setup_host_resources(max_ppn)

	def setup_host_resources(self, max_ppn):
		hl = expand_host_list(os.environ['QFW_QPM_ASSIGNED_HOSTS'])
		for h in hl:
			comp = h.split(':')
			if len(comp) == 1:
				self.free_hosts[comp[0]] = max_ppn
			elif len(comp) == 2:
				self.free_hosts[comp[0]] = int(comp[1])

	def create_circuit(self, info):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		cid = str(uuid.uuid4())
		self.circuits[cid] = Circuit(cid, info, self.free_resources_and_oor)
		self.circuits[cid].set_ready()
		logging.debug(f"{cid} added to circuit database")
		return cid

	def delete_circuit(self, cid):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		if cid not in self.circuits:
			return
		circ = self.circuits[cid]
		if circ.can_delete():
			del self.circuits[cid]
		else:
			circ.set_deletion()

	def consume_resources(self, circ):
		info = circ.info
		np = info['np']
		num_hosts = int(np / self.max_ppn)
		if not num_hosts:
			num_hosts = 1

		# determine if we have enough hosts to run this circuit
		# If the number of hosts required is more than the total number
		# of hosts then we can't run the circuit.
		logging.debug(f"Available resources = {self.free_hosts}")
		if num_hosts > len(self.free_hosts.keys()):
			raise DEFwOutOfResources("Not enough nodes to run simulation")

		tmp_resources = {}
		consumed_res = {}
		itrnp = 0
		for host in self.free_hosts.keys():
			if np == 0:
				break;
			tmp_resources[host] = self.free_hosts[host]
			if self.free_hosts[host] >= np:
				self.free_hosts[host] = self.free_hosts[host] - np
				consumed_res[host] = np
				itrnp += np
				np = 0
			elif self.free_hosts[host] < np and self.free_hosts[host] != 0:
				np -= self.free_hosts[host]
				itrnp += self.free_hosts[host]
				consumed_res[host] = self.free_hosts[host]
				self.free_hosts[host] = 0
		if np != 0:
			# restore whatever was consumed
			for k, v in tmp_resources.items():
				self.free_hosts[k] = v
			raise DEFwOutOfResources("Not enough nodes to run simulation")

		circ.info['hosts'] = consumed_res
		logging.debug(f"Circuit consumed: {consumed_res}")

	def process_oor_queue(self):
		while True:
			if self.oor_queue.empty():
				break
			# get the top of the queue without popping it in case there
			# are no more resources.
			cid = self.oor_queue[0]
			circ = self.circuits[cid]
			try:
				self.common_run(cid)
				# now that we have the resources for the circuit secured
				# pop that entry off the queue.
				cid = self.oor_queue.get(block=False)
				self.async_run(cid, circ.common_run)
			except DEFwOutOfResources:
				oor_queue.put(cid)
				break

	def free_resources(self, circ):
		res = circ.info['hosts']
		for host in res.keys():
			if host not in self.free_hosts:
				raise DEFwError(f"Circuit has untracked host: {host}")
			if res[host] + self.free_hosts[host] > self.max_ppn:
				raise DEFwError("Returning more resources than originally had")
			self.free_hosts[host] += res[host]
		circ.set_done()
		cid = circ.get_cid()
		logging.debug(f"Deleting circuit {cid}")
		self.delete_circuit(cid)

	def free_resources_and_oor(self, circ):
		self.free_resources(circ)
		# When resources are free, go through the queue and try
		# to consume circuits from that queue until you run out of
		# resources again.
		self.process_oor_queue()

	def common_run(self, cid):
		circuit = self.circuits[cid]
		self.consume_resources(circuit)
		circuit.set_resources_consumed()
		logging.debug(f"Running {cid}\n{circuit.info}")
		return circuit

	def sync_run(self, cid, common_run=None):
		global qpm_initialized

		if not common_run:
			common_run = self.common_run
		else:
			self.common_run = common_run

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = common_run(cid)
		try:
			result = self.qrc.sync_run(circuit)
		except Exception as e:
			self.free_resources(circuit)
			raise e
		self.free_resources(circuit)
		logging.debug(f"circuit {circuit.get_cid()} completed with output {result}")
		return result

	def async_run(self, cid, common_run=None):
		global qpm_initialized

		if not common_run:
			common_run = self.common_run
		else:
			self.common_run = common_run

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		circuit = common_run(cid)

		try:
			self.qrc.async_run(circuit)
		except DEFwOutOfResources:
			# queue circuit on a local out of resources queue
			self.free_resources(circuit)
			oor_queue.put(cid)
		except Exception as e:
			self.free_resources_and_oor(circuit)
			raise e

	def read_cq(self, cid=None):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		r = self.qrc.read_cq(cid)

		if not r:
			if cid:
				raise DEFwInProgress(f"{cid} still in progress")
			else:
				raise DEFwInProgress("No ready QTs")

		return r

	def peek_cq(self, cid=None):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		r = self.qrc.peak_cq()

		if not r:
			if cid:
				raise DEFwInProgress(f"{cid} still in progress")
			else:
				raise DEFwInProgress("No ready QTs")

		return r

	def status(self, cid):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		return self.qrc.status(cid)

	def is_ready(self):
		global qpm_initialized

		if not qpm_initialized:
			raise DEFwNotReady("QPM has not initialized properly")

		return True

	def query_helper(self, type_bits, caps_bits, svc_name, svc_desc):
		from api_qpm import QPMType, QPMCapability
		from defw_agent_info import get_bit_list, get_bit_desc, \
									Capability, DEFwServiceInfo
		t = get_bit_list(type_bits, QPMType)
		c = get_bit_list(caps_bits, QPMCapability)
		cap = Capability(type_bits, caps_bits, get_bit_desc(t, c))
		info = DEFwServiceInfo(svc_name, svc_desc,
							   self.__class__.__name__,
							   self.__class__.__module__,
							   cap, -1)
		return info

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services=None):
		if self.qrc:
			self.qrc.shutdown()
			self.qrc = None
		pass

	def schedule_shutdown(self, timeout=5):
		logging.debug(f"Shutting down in {timeout} seconds")
		time.sleep(timeout)
		me.exit()

	def shutdown(self):
		logging.debug("Scheduling QPM Shutdown")
		if self.qrc:
			self.qrc.shutdown()
			self.qrc = None
		#ss = threading.Thread(target=self.schedule_shutdown, args=())
		#ss.start()

	def test(self):
		return "****UTIL QPM Test Successful****"

