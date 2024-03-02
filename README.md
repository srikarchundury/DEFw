# Distributed Execution Framework

Environment Variables
DEFW_CONFIG_PATH: Path to YAML configuration file
LD_LIBRARY_PATH: Path DEFw libraries
DEFW_PATH: Path to the DEFw top directory
DEFW_AGENT_NAME: DEFw instance name. Should be unique
DEFW_LISTEN_PORT: port the agent listens on
DEFW_AGENT_TYPE: type of the agent. One of: agent, service or resmgr
DEFW_PARENT_ADDR: The address of the parent DEFw should connect to
DEFW_PARENT_PORT: The port of the parent DEFw should connect on
DEFW_PARENT_NAME: The parent name
DEFW_PARENT_HNAME: The parent hostname
DEFW_SHELL_TYPE: How to run the DEFw. One of: interactive, cmdline or daemon
DEFW_ONLY_LOAD_MODULE: Comma separated list of modules to load
DEFW_LOG_LEVEL: debug level. One of: all, message, debug, error
DEFW_LOG_DIR: Directory where logging files and other data is stored

Beside DEFW_CONFIG_PATH all the other environment variables are used in
the YAML configuration file directly. This allows us to have only one YAML
file used for everything.

QFW_BASE_QRC_PORT: The base QRC listen port
QFW_NUM_QRC: The number of QRC processes to start

