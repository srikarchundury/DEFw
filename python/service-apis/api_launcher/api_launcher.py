from defw_remote import BaseRemote

class Launcher(BaseRemote):
	def __init__(self, ep):
		super().__init__(target=ep)

	# returns only after the process has been launched
	def launch(self, proc, path=''):
		pass

