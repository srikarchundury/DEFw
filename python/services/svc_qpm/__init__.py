from defw_util import prformat, fg, bg
from .svc_qpm import QPM, QRC_list, QRCInstance
import sys

# This is used by the infrastructure to display information about
# the service module. The name is also used as a key through out the
# infrastructure. Without it the service module will not load.
svc_info = {'name': 'QPM',
			'description': 'Quantum Platform Manager',
			'version': 1.0}

# This is used by the infrastructure to define all the service classes.
# Each class should be a separate service. Each class should implement the
# following methods:
#	query()
#	reserve()
#	release()
service_classes = [QPM]

g_initialized = False

def expand_host_list(expr):
	host_list = []

	open_br = expr.find('[')
	close_br = expr.find(']', open_br)
	if open_br == -1 and close_br == -1:
		return [expr]

	if open_br == -1 or close_br == -1:
		return []

	rangestr = expr[open_br+1 : close_br]

	node = expr[:open_br]

	ranges = rangestr.split(',')

	for r in ranges:
		cur = r.split('-')
		if len(cur) == 2:
			pre = "{:0%dd}" % len(cur[0])
			for idx in range(int(cur[0]), int(cur[1])+1):
				host_list.append(f'{node}{pre.format(idx)}')
		elif len(cur) == 1:
			pre = "{:0%dd}" % len(cur[0])
			host_list.append(f'{node}{pre.format(int(cur[0]))}')

	return host_list

def spawn_qrc(res):
	from defw import resmgr, connect_to_services

	# . Add each QRC endpoint on the QPM list
	# . QPM will subsequently post messages on each of the QRCs
	ep = resmgr.reserve(me.my_endpoint(), res)
	h = connect_to_services(ep)
	class_obj = getattr(service_apis['launcher'], r['laucher']['api'])
	launcher_api = class_obj(ep[0])
	# run_cmd doesn't return until the QRC is up and running
	QRC_list.append(QRCInstance(launcher_api.run_cmd('defwp -s QRC')))
	h.disconnect()
	resmgr.release(r)


def start_qrcs(num_qrc, host_list):
	global g_initialized

	len_host_list = len(host_list)

	# get a list of all the launchers
	# make sure that each node in the host list has a launcher.
	#	if not wait until all nodes have launchers
	# For each launcher query the number of GPUs
	# Based on the number of GPUs tell the launcher to start a QRC per GPU
	# and bind it to the GPU
	num_itr = 0
	complete = False
	found_hosts = []
	found_resource = []
	res = resmgr.get_services('launcher')
	while (num_itr < 10):
		for r in res:
			if r['residence'].hostname in host_list and \
			   r['residence'].hostname not in found_hosts:
				found_hosts.append(r['residence'].hostname)
				found_resources.append(r)
		if not len(found_hosts) == len_host_list and num_itr < 10:
			num_itr += 1
			sleep(1)
		else:
			complete = True

	if not complete:
		raise DEFwCommError("Failed to connect to all launchers")

	# TODO: in the future take into account the number of gpus. For now we
	# assume 8 GPUs per node because that's what's on frontier. So we will
	# distribute evenly based on that
	# . Spawn the QRCs Distributing them as evenly as possible among all the nodes
	#   taking into consideration the gpu info
	num_qrc_pn = int(num_qrc/len_host_list)
	if num_qrc_pn == 0:
		remaining_qrc = num_qrc
		# we have more nodes than processes. Put one process per node
		for r in found_resources and remaining_qrc > 0:
			spawn_qrc(r)
			remaining_qrc -= 1
	else:
		for r in found_resources:
			for i in range(0, num_qrc_pn):
				spawn_qrc(r)

	g_initialized = True

def initialize():
	global g_initialized

	if g_initialized:
		return

	# . Read a predefined environment variable QFW_NUM_QRC
	# . Read the SLURM node list: SLURM_NODELIST
	#
	if 'QFW_NUM_QRC' in os.environ:
		num_qrc = int(os.environ['QFW_NUM_QRC'])
	else:
		num_qrc = 1

	if 'SLURM_NODELIST' in os.environ:
		host_list = expand_host_list(os.environ['SLURM_NODELIST'])
	else:
		import socket
		host_list = [socket.gethostname()]

	start_qrcs(num_qrc, host_list)

def uninitialize():
	pass
