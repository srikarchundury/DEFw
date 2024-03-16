from defw_remote import BaseRemote

class QRC(BaseRemote):
	def __init__(self, ep):
		super().__init__(target=ep)

	def sync_run(self, cid, info):
		pass

	def async_run(self, cid, info):
		pass

	def read_cq(self, cid=None):
		pass

	def test(self):
		pass
