export DEFW_CONFIG_PATH=$DEFW_PATH/python/config/defw_generic.yaml
export LD_LIBRARY_PATH=$DEFW_PATH/src/:$LD_LIBRARY_PATH
export DEFW_AGENT_NAME=qpm
export DEFW_LISTEN_PORT=8095
export DEFW_AGENT_TYPE=service
export DEFW_PARENT_HOSTNAME=$(hostname)
export DEFW_PARENT_PORT=8090
export DEFW_PARENT_NAME=resmgr
export DEFW_SHELL_TYPE=interactive
#export DEFW_SHELL_TYPE=daemon
export DEFW_LOG_LEVEL=all
export DEFW_DISABLE_RESMGR=no
export DEFW_LOG_DIR=/tmp/${DEFW_AGENT_NAME}
export DEFW_ONLY_LOAD_MODULE=svc_qb_qpm

