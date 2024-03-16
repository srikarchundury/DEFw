from defw_util import prformat, fg, bg
from defw_exception import DEFwError
from .svc_qrc import *
import sys

# This is used by the infrastructure to display information about
# the service module. The name is also used as a key through out the
# infrastructure. Without it the service module will not load.
svc_info = {'name': 'QRC',
			'description': 'Quantum Runtime Controller',
			'version': 1.0}

# This is used by the infrastructure to define all the service classes.
# Each class should be a separate service. Each class should implement the
# following methods:
#	query()
#	reserve()
#	release()
service_classes = [QRC]

def initialize():
	prformat(fg.green+fg.bold, "registering the Quantum Runtime Controller")

def uninitialize():
	# TODO: we need a way to kill all living processes on uninitialization
	prformat(fg.green+fg.bold, "unregistering the Quantum Runtime Controller")
