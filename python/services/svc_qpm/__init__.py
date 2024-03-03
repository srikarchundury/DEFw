from defw_exception import DEFwCommError, DEFwAgentNotFound
from .svc_qpm import QPM, QRC_list, QRCInstance, g_qpm_initialized
import cdefw_global
import defw
import sys, os, threading, logging
from time import sleep

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

g_launchers = {}
g_shutdown = False

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

def spawn_qrc(res, port):
	#from defw import resmgr, connect_to_services

	my_ep = defw.me.my_endpoint()
	qrc_name = 'DEFwLauncher'+str(port)

	env =  {'DEFW_AGENT_NAME': qrc_name,
			'DEFW_LISTEN_PORT': str(port),
			'DEFW_ONLY_LOAD_MODULE': 'svc_qrc',
			'DEFW_SHELL_TYPE': 'daemon',
			'DEFW_AGENT_TYPE': 'service',
			'DEFW_PARENT_ADDR': my_ep.addr,
			'DEFW_PARENT_PORT': str(my_ep.port),
		 #'DEFW_PARENT_PORT': str(8474),
			'DEFW_PARENT_NAME': my_ep.name,
			'DEFW_LOG_DIR': os.path.join(os.path.split(cdefw_global.get_defw_tmp_dir())[0], qrc_name),
			'DEFW_PARENT_HNAME': my_ep.hostname}

	# . Add each QRC endpoint on the QPM list
	# . QPM will subsequently post messages on each of the QRCs
	ep = defw.resmgr.reserve(defw.me.my_endpoint(), res)
	# TODO have to have a corresponding disconnect from service
	logging.debug(f"connect to launcher {ep}")
	defw.connect_to_services(ep)
	class_obj = getattr(defw.service_apis['Launcher'],
						res[list(res.keys())[0]]['api'])
	launcher_api = class_obj(ep[0])

	pid = launcher_api.launch("/home/a2e/ORNL/Quantum/QFw/defw/src/defwp", env=env)
	logging.debug(f"Launched {qrc_name} with {pid}")
	qrc_inst = QRCInstance(pid)
	QRC_list.append(qrc_inst)
	if launcher_api in g_launchers.keys():
		g_launchers[launcher_api].append(qrc_inst)
	else:
		g_launchers[launcher_api] = [qrc_inst]

	# Make sure that QRC has connected to me.
	wait = 0
	started = False
	while wait < 5:
		if qrc_name in defw.service_agents:
			started = True
			break
		logging.debug("Waiting for QRC to start up")
		wait += 1
		sleep(1)
	if not started:
		uninitialize()
		raise DEFwAgentNotFound(f"{qrc_name} did not start")
	qrc_ep = defw.service_agents[qrc_name].get_ep()
	qrc_api = defw.service_apis['QRC'].QRC(qrc_ep)
	qrc_inst.add_qrc(qrc_api)

def start_qrcs(num_qrc, host_list):
	import yaml
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
	found_launchers = []
	res = defw.resmgr.get_services('Launcher')
	while (num_itr < 10 and len(res) > 0):
		for k, r in res.items():
			if r['residence'].hostname in host_list and \
			   r['residence'].hostname not in found_hosts:
				found_hosts.append(r['residence'].hostname)
				found_launchers.append({k:r})
		if not len(found_hosts) == len_host_list and num_itr < 10:
			num_itr += 1
			logging.debug("Waiting to connect to launcher")
			sleep(1)
		else:
			complete = True
			break

	if not complete:
		raise DEFwCommError("Failed to connect to all launchers")

	# TODO: in the future take into account the number of gpus. For now we
	# assume 8 GPUs per node because that's what's on frontier. So we will
	# distribute evenly based on that.
	# . Spawn the QRCs Distributing them as evenly as possible among all the nodes
	#   taking into consideration the gpu info
	if 'QFW_BASE_QRC_PORT' in os.environ:
		base_port = os.environ['QFW_BASE_QRC_PORT']
	else:
		base_port = 9000
	num_qrc_pn = int(num_qrc/len_host_list)
	if num_qrc_pn == 0:
		remaining_qrc = num_qrc
		# we have more nodes than processes. Put one process per node
		for r in found_launchers and remaining_qrc > 0:
			base_port += 1
			spawn_qrc(r, base_port)
			remaining_qrc -= 1
	else:
		for r in found_launchers:
			for i in range(0, num_qrc_pn):
				base_port += 1
				spawn_qrc(r, base_port)

	logging.debug("QPM Initialized")
	g_qpm_initialized = True

def qpm_complete_init():
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

def qpm_wait_resmgr():
	global g_shutdown

	while not defw.resmgr and not g_shutdown:
		logging.debug("still waiting for resmgr to come up")
		sleep(1)
	if not g_shutdown:
		qpm_complete_init()

def initialize():
	global g_qpm_initialized

	if g_qpm_initialized:
		return

	if not defw.resmgr:
		# we haven't connected to the resmgr yet. Spin up a thread and
		# wait for it to connect before finishing up the initialization
		svc_qpm_thr = threading.Thread(target=qpm_wait_resmgr, args=())
		svc_qpm_thr.start()
		return

	qpm_complete_init()

def uninitialize():
	global g_shutdown

	g_shutdown = True
	for launcher, qrcs in g_launchers.items():
		for qrc in qrcs:
			launcher.kill(qrc.pid)
	# TODO: Disconnect from launchers
