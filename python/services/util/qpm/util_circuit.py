from defw_agent_info import *
from defw_util import round_half_up, round_to_nearest_power_of_two
import logging, os

# Maximum number of processes per node
MAX_PPN = 8
# Maximum number of qubits per process
MAX_QUBITS_PP = 10

class CircuitStates:
	UNDEF = 0
	MARKED_FOR_DELETION = 1
	EXEC_DONE = 2
	DONE = 3
	READY = 4
	RUNNING = 5
	FAIL = 6

class Circuit:
	def __init__(self, cid, info):
		self.__state = CircuitStates.UNDEF
		self.__cid = cid
		self.info = info
		self.setup_circuit_run_details()
		self.exec_time = -1

	def setup_circuit_run_details(self):
		# TODO: Make MPI configuration decisions based
		# on the circuit meta data

		try:
			self.info['exec'] = os.environ['QFW_LAUNCHER_BIN']
		except:
			self.info['exec'] = 'mpirun'

		try:
			# QFW_MODULE_USE_PATH is in the format:
			#	path/to/use1:path/to/use2:...
			module_use = os.environ['QFW_MODULE_USE_PATH']
			self.info['modules'] = {'use': module_use.split(':')}
			# QFW_MODULE_LOADS is in the format:
			#	mod1,mod2,...
			mods = os.environ['QFW_MODULE_LOADS']
			self.info['modules']['mods'] =  mods.split(',')
		except:
			self.info['modules'] = {}
			self.info['modules']['use'] = ''
			self.info['modules']['mods'] = ''

		# These must be defined
		try:
			self.info['provider'] = os.environ['QFW_OMPI_LIBFABRIC_PROV']
		except:
			self.info['provider'] = 'shm+cxi:linkx'

		try:
			self.info['mapping'] = os.environ['QFW_OMPI_MAPPING']
		except:
			self.info['mapping'] = 'ppr:1:l3cache'
			#self.info['mapping'] = 'l3cache:pe=6'

		self.info['qfw_dvm_uri_path'] = \
				f"file:{os.environ['QFW_DVM_URI_PATH']}"

		# each 10 qubits requires 1 node added to the simulation
		np = round_half_up(self.info['num_qubits'] / MAX_QUBITS_PP)
		if np < 1:
			np = 1
		else:
			np = round_to_nearest_power_of_two(np)
		self.info['np'] = np
		logging.debug(f"Setting number of processes to: {self.info['np']} " \
					  f"for num qubits: {self.info['num_qubits']}")

	def getState(self):
		return self.__state

	def get_cid(self):
		return self.__cid

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

	def set_exec_done(self):
		return self.set_state(CircuitStates.EXEC_DONE)

	def set_done(self):
		return self.set_state(CircuitStates.DONE)

	def set_fail(self):
		return self.set_state(CircuitStates.FAIL)

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

