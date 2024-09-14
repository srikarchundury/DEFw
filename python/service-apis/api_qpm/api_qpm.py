from defw_remote import BaseRemote

class QPM(BaseRemote):
	def __init__(self, si):
		super().__init__(service_info = si)

	def create_circuit(self, info):
		pass

	def delete_circuit(self, cid):
		pass

	def sync_run(self, cid):
		pass

	def async_run(self, cid):
		pass

	def status(self, cid):
		pass

	def is_ready(self):
		pass

	def read_cq(self, cid=None):
		pass

	def peek_cq(self, cid=None):
		pass

	def test(self):
		pass

	def shutdown(self):
		pass

