from defw_exception import DEFwCommError, DEFwAgentNotFound
from defw_util import expand_host_list
from .svc_qpm import QPM, QRCInstance
import cdefw_global
import defw
import sys, os, threading, logging
from time import sleep

sys.path.append(os.path.split(os.path.abspath(__file__))[0])
import qpm_common as common

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

def connect_to_launcher(res):
	# . Add each QRC endpoint on the QPM list
	# . QPM will subsequently post messages on each of the QRCs
	ep = defw.resmgr.reserve(defw.me.my_endpoint(), res)
	# TODO have to have a corresponding disconnect from service
	logging.debug(f"connect to launcher {ep}")
	defw.connect_to_services(ep)
	class_obj = getattr(defw.service_apis['Launcher'],
						res[list(res.keys())[0]]['api'])
	launcher_api = class_obj(ep[0])
	return launcher_api

def wait_for_all_qrcs():
	global g_timeout
	# Make sure that the QRCs have connected to me.
	wait = 0
	started = False
	qrc_key = ''
	total = len(common.QRC_list)
	connected = 0
	while wait < g_timeout:
		if total == connected:
			started = True
			break
		for qrc_inst in common.QRC_list:
			if qrc_inst.status == QRCInstance.STATUS_CONNECTED:
				continue
			qrc_key = defw.service_agents.get_key_by_name(qrc_inst.name)
			if not qrc_key:
				continue
			qrc_ep = defw.service_agents[qrc_key].get_ep()
			qrc_api = defw.service_apis['QRC'].QRC(qrc_ep)
			qrc_inst.add_qrc(qrc_api)
			qrc_inst.status = QRCInstance.STATUS_CONNECTED
			connected += 1
			logging.debug(f"QRC {qrc_inst.name} with key {qrc_key} connected")

		logging.debug("Waiting for QRC to start up")
		wait += 1
		sleep(1)
	if not started:
		uninitialize()
		raise DEFwAgentNotFound(f"QRCs did not start")
	logging.debug("All QRCs connected")

def spawn_qrc(launcher_api, port):
	my_ep = defw.me.my_endpoint()
	qrc_name = 'DEFwQRC'+str(port)

	env =  {'DEFW_AGENT_NAME': qrc_name,
			'DEFW_LISTEN_PORT': str(port),
			'DEFW_TELNET_PORT': str(port+1),
			'DEFW_ONLY_LOAD_MODULE': 'svc_qrc',
			'DEFW_LOAD_NO_INIT': 'svc_launcher',
			'DEFW_SHELL_TYPE': 'daemon',
			'DEFW_AGENT_TYPE': 'service',
			'DEFW_PARENT_ADDR': my_ep.addr,
			'DEFW_PARENT_PORT': str(my_ep.port),
			'DEFW_PARENT_NAME': my_ep.name,
			'DEFW_DISABLE_RESMGR': "no",
			'DEFW_LOG_DIR': os.path.join(os.path.split(cdefw_global.get_defw_tmp_dir())[0], qrc_name),
			'DEFW_PARENT_HOSTNAME': my_ep.hostname}

	# defwp can be in PATH
	try:
		bin_path = os.environ['QFW_QRC_BIN_PATH']
	except:
		bin_path = "defwp"
	pid = launcher_api.launch(bin_path, env=env)
	logging.debug(f"Launched {qrc_name} with {pid}")
	qrc_inst = QRCInstance(pid, qrc_name)
	common.QRC_list.append(qrc_inst)
	if launcher_api in g_launchers.keys():
		g_launchers[launcher_api].append(qrc_inst)
	else:
		g_launchers[launcher_api] = [qrc_inst]

def start_qrcs(num_qrc, host_list):
	import yaml
	global g_timeout
	len_host_list = len(host_list)

	# get a list of all the launchers
	# make sure that each node in the host list has a launcher.
	#	if not wait until all nodes have launchers
	# For each launcher query the number of GPUs
	# Based on the number of GPUs tell the launcher to start a QRC per GPU
	# and bind it to the GPU
	wait = 0
	res = {}
	complete = False
	found_hosts = []
	found_launchers = []
	logging.debug(f"Here are the available launchers: {res}")
	while len(res) >= 0:
		wait += 1
		if wait >= g_timeout:
			break
		res = defw.resmgr.get_services('Launcher')
		logging.debug(f"Launcher resources return {res}")
		if not res:
			sleep(5)
			continue
		for k, r in res.items():
			if r['residence'].hostname in host_list and \
			   r['residence'].hostname not in found_hosts:
				found_hosts.append(r['residence'].hostname)
				found_launchers.append({k:r})
		if len(found_hosts) != len_host_list:
			logging.debug("Waiting to connect to launcher")
			sleep(1)
		else:
			complete = True
			break

	if not complete:
		raise DEFwCommError("Failed to connect to all launchers")

	launcher_apis = []
	for launcher in found_launchers:
		launcher_apis.append(connect_to_launcher(launcher))

	logging.debug(f"Here are the launcher APIs: {launcher_apis}")

	# TODO: in the future take into account the number of gpus. For now we
	# assume 8 GPUs per node because that's what's on frontier. So we will
	# distribute evenly based on that.
	# . Spawn the QRCs Distributing them as evenly as possible among all the nodes
	#   taking into consideration the gpu info
	if 'QFW_BASE_QRC_PORT' in os.environ:
		base_port = int(os.environ['QFW_BASE_QRC_PORT'])
	else:
		base_port = 9000
	num_qrc_pn = int(num_qrc/len_host_list)
	if num_qrc_pn == 0:
		remaining_qrc = num_qrc
		# we have more nodes than processes. Put one process per node
		for api in launcher_apis and remaining_qrc > 0:
			base_port += 1
			spawn_qrc(api, base_port)
			remaining_qrc -= 1
	else:
		for api in launcher_apis:
			for i in range(0, num_qrc_pn):
				base_port += 1
				spawn_qrc(api, base_port)

	wait_for_all_qrcs()

	logging.debug(f"QPM Initialized: {common.QRC_list}")
	common.g_qpm_initialized = True

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
	global g_timeout

	if common.g_qpm_initialized:
		return

	try:
		g_timeout = int(os.environ['QFW_STARTUP_TIMEOUT'])
	except:
		g_timeout = 40

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
			try:
				launcher.kill(qrc.pid)
			except:
				pass
	# TODO: Disconnect from launchers
