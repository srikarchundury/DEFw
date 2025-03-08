from defw_remote import BaseRemote

VERSION = 0.1

class Event:
	def __init__(self, evtype, ev):
		self.__evtype = evtype
		self.__ev = ev

	def get_evtype(self):
		return self.__evtype

	def get_event(self):
		return self.__ev

# Allow the remote end to push events only
class BaseEventAPI(BaseRemote):
	def __init__(self, class_id=None, target=None, thread_safe=True, *args, **kwargs):
		super().__init__(class_id=class_id, target=target, *args, **kwargs)

	def push(self, event):
		pass

