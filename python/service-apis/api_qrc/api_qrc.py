from defw_remote import BaseRemote

class QRC(BaseRemote):
	def __init__(self, ep):
		super().__init__(target=ep)

	def sync_run(self, cid, qasm):
		pass

	def async_run(self, cid, qasm):
		pass

	def read_cq(self, cid=None):
		pass


