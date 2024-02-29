from defw_agent_info import *
from defw_util import prformat, fg, bg
from defw import me
import logging, uuid, time, queue, threading, logging
from defw_exception import DEFwError

CID_COUNTER = 0
QCR_VERBOSE = 1
QRC_list = []

class CircuitStates:
	UNDEF = 0
	READY = 1
	RUNNING = 2
	MARKED_FOR_DELETION = 3
	DONE = 4

class QRCInstance:
	def __init__(self, qrc):
		self.instance = qrc
		self.circuit_results = []
		self.load = 0

class Circuit:
	def __init__(self):
		self.__state = CircuitStates.UNDEF
		self.__cid = None
		self.qasm = None
		self.assigned_qrc = None

	def getState(self):
		return self.__state

	def set_state(self, state):
		# State is monotonically increasing
		if self.__state > state:
			return False
		self.__state = state
		return True

	def set_ready(self):
		return self.set_state(CircuitStates.READY)

	def set_running(self):
		return self.set_state(CircuitStates.RUNNING)

	def set_deletion(self):
		return self.set_state(CircuitStates.MARKED_FOR_DELETION)

	def set_done(self):
		self.assigned_qrc = None
		return self.set_state(CircuitStates.DONE)

	def can_delete(self):
		if self.__state <= CircuitStates.READY:
			return True
		return False

	def status(self):
		if self.__state == CircuitStates.READY:
			return 'READY'
		if self.__state == CircuitStates.RUNNING:
			return 'RUNNING'
		if self.__state == CircuitStates.MARKED_FOR_DELETION:
			return 'DELETING'
		if self.__state == CircuitStates.DONE:
			return 'DONE'
		return 'BUG'

class QPM:
	def __init__(self, start=True):
		self.circuits = {}
		self.runner_queue = queue.Queue()
		self.circuit_results = []
		self.qrc_list = QRC_list
		self.qrc_rr = 0

	def create_circuit(self, qasm, nbits=1, endpoint=None):
		cid = str(uuid.uuid4())
		self.circuits[cid] = Circuit()
		self.circuits[cid].qasm = qasm
		self.circuits[cid].set_ready()
		return cid

	def delete_circuit(self, cid):
		if cid not in self.circuits:
			return
		circ = self.circuits[cid]
		if circ.can_delete():
			del self.circuits[cid]
		else:
			circ.set_deletion()

	def sync_run(self, cid):
		circuit = self.circuits[cid]
		qrc = self.qrc_list[len(self.qrc_list) % self.qrc_rr]
		qrc.load += 1
		self.qrc_rr += 1

		return qrc.instance.sync_run(cid, circuit.qasm)

	def async_run(self, cid):
		circuit = self.circuits[cid]
		qrc = self.qrc_list[len(self.qrc_list) % self.qrc_rr]
		qrc.load += 1
		circuit.assigned_qrc = qrc
		circuit.set_running()
		self.qrc_rr += 1

		return qrc.instance.async_run(cid, circuit.qasm)

	def read_all_qrc_cqs(self):
		for qrc in self.qrc_list:
			while (res = qrc.instance.read_cq()):
				qrc.circuit_results.append(res)
				self.circuit[res['cid']].set_done()

	def read_cq(self, cid=None):
		self.read_all_qrc_cqs()
		if cid:
			if cid not in self.circuits:
				return None
			circ = self.circuits[cid]
			qrc = circ.assigned_qrc
			i = 0
			for e in qrc.circuit_results:
				if cid == e['cid']:
					r = qrc.circuit_results.pop(i)
					return r
				i += 1
		else:
			for qrc in self.qrc_list:
				if len(qrc.circuit_results) > 0:
					r = qrc.circuit_results.pop(0)
					return r
		return None

	def peek_cq(self, cid=None):
		self.read_all_qrc_cqs()
		if cid:
			if cid not in self.circuits:
				return None
			circ = self.circuits[cid]
			qrc = circ.assigned_qrc
			i = 0
			for e in qrc.circuit_results:
				if cid == e['cid']:
					return e
				i += 1
		else:
			for qrc in self.qrc_list:
				if len(qrc.circuit_results) > 0:
					return qrc.circuit_results[0]
		return None

	def status(self):
		self.read_all_qrc_cqs()
		r = {}
		for cid, circ in self.circuits.items():
			r[cid] = circ.status()
		return r

	def query(self):
		from . import svc_info
		cap = Capability("QPM", "Quantum Platform Manager", 1)
		svc = ServiceDescr(svc_info['name'], svc_info['description'], [cap], 1)
		info = DEFwAgentInfo(self.__class__.__name__,
						  self.__class__.__module__, [svc])
		return info

	def reserve(self, svc, client_ep, *args, **kwargs):
		logging.debug(f"{client_ep} reserved the {svc}")

	def release(self, services):
		self.runner_shutdown = True

