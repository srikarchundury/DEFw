#ifndef IFW_PYTHON_H
#define IFW_PYTHON_H

#include <pthread.h>
#include "defw.h"

typedef struct python_thread_data_s {
	char **argv;
} python_thread_data_t;

/*
 * python_init
 *    initialize the python interpreter
 *    It can then be run interactively or not
 */
defw_rc_t python_init(void);

/*
 * python_finalize
 *   Finalize the python interpreter
 */
defw_rc_t python_finalize(void);

/*
 * python_run_cmd_line
 *   this is intended to run python as you would from the command line
 */
defw_rc_t python_run_cmd_line(int argc, char *argv[], char *module, char *cmd);

/*
 * python_exec
 *    Run a python code. This is not meant for complex use
 */
defw_rc_t python_exec(char *code);

/*
 * python_run_interactive_shell
 *    Run the interactive shell
 */
defw_rc_t python_run_interactive_shell(void);

/*
 * python_collect_agent_core
 *   Collect core information from the specified agent
 */
defw_rc_t python_collect_agent_core(char *ip);

/*
 * python_handle_[request | response]
 *   Received an RPC now execute the operation in the python interpreter
 */
defw_rc_t python_handle_request(char *rpc, char *uuid);
defw_rc_t python_handle_response(char *rpc, char *uuid);

/*
 * python_handle_connect_complete
 *	A connection requested by python has completed
 */
defw_rc_t python_handle_connect_complete(defw_rc_t status, char *uuid);

/*
 * python_update_interactive_shell
 *	update the interactive shell environment
 */
void python_update_interactive_shell(void);

/*
 * python_refresh_agent
 *   After an agent connects trigger python to refresh its state
 */
defw_rc_t python_refresh_agent(void);

#endif /* IFW_PYTHON_H */
