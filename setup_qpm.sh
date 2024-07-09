export DEFW_PATH=/sw/frontier/qhpc/QFw/DEFw
export DEFW_CONFIG_PATH=$DEFW_PATH/python/config/defw_generic.yaml
export LD_LIBRARY_PATH=$DEFW_PATH/src/:$LD_LIBRARY_PATH
export DEFW_AGENT_NAME=qpm
export DEFW_LISTEN_PORT=8095
export DEFW_AGENT_TYPE=service
export DEFW_PARENT_HOSTNAME=borg016
export DEFW_PARENT_PORT=8090
export DEFW_PARENT_NAME=resmgr
export DEFW_SHELL_TYPE=interactive
export DEFW_LOG_LEVEL=all
export DEFW_LOG_DIR=/tmp/${DEFW_AGENT_NAME}
export DEFW_ONLY_LOAD_MODULE=svc_qpm,api_launcher,api_qrc
export QFW_BASE_QRC_PORT=9100
export QFW_NUM_QRC=1
export QFW_QRC_BIN_PATH=$DEFW_PATH"/src/defwp"
export QFW_QPM_ASSIGNED_HOSTS=borg016
export QFW_MODULE_USE_PATH="/sw/frontier/ums/ums024/cce/15.0.0/modules/"
export QFW_PATH=/sw/frontier/qhpc/QFw
export QFW_BIN_PATH=$QFW_PATH/bin

