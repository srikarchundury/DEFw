#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <pthread.h>
#include <errno.h>
#include <unistd.h>
#include <getopt.h>
#include <fcntl.h>
#include <string.h>
#include <strings.h>
#include <sys/time.h>
#include <sys/socket.h>
#include "defw_listener.h"
#include "defw_message.h"
#include "defw_python.h"
#include "defw.h"
#include "defw_sl.h"
#include "libdefw_agent.h"

extern defw_config_params_t g_defw_cfg;
FILE *out;
char *outlog;
pthread_spinlock_t log_spin_lock;

defw_rc_t defw_start(int argc, char *argv[], bool daemon)
{
	pthread_t l_thread_id;
	defw_rc_t rc;

	if (daemon) {
		pid_t process_id = 0;
		pid_t sid = 0;

		/* create the child process */
		process_id = fork();
		if (process_id < 0) {
			PERROR("Failed to run defw as deamon");
			return EN_DEFW_RC_ERR_THREAD_STARTUP;
		}

		if (process_id > 0) {
			/*
			 * We're in the parent process so let's kill it
			 * off
			 */
			PDEBUG("Shutting down parent process");
			exit(DEFW_EXIT_NORMAL);
		}

		umask(0);
		sid = setsid();
		if (sid < 0) {
			PERROR("forking child failed");
			return EN_DEFW_RC_ERR_THREAD_STARTUP;
		}

		rc = chdir("/");
		close(STDIN_FILENO);
		close(STDOUT_FILENO);
		close(STDERR_FILENO);
		if (rc) {
			PERROR("chdir failed");
			return EN_DEFW_RC_ERR_THREAD_STARTUP;
		}
	}

	memset(&g_defw_cfg, 0, sizeof(g_defw_cfg));

	pthread_spin_init(&log_spin_lock, PTHREAD_PROCESS_PRIVATE);

	/* generate global uuid for this instance */
	uuid_generate(g_defw_cfg.uuid);

	defw_agent_init();

	rc = python_init();
	if (rc) {
		PERROR("Failed to initialize Python Module");
		return rc;
	}

	/* create the log file */
	out = stdout;
	if (strlen(g_defw_cfg.tmp_dir) == 0)
		getcwd(g_defw_cfg.tmp_dir, sizeof(g_defw_cfg.tmp_dir));
	outlog = calloc(strlen(g_defw_cfg.tmp_dir) + strlen(OUT_LOG_NAME) + 2, 1);
	if (!outlog) {
		PERROR("out of memory");
		return EN_DEFW_RC_LOG_CREATION_FAILURE;
	}
	sprintf(outlog, "%s/%s", g_defw_cfg.tmp_dir, OUT_LOG_NAME);
	out = fopen(outlog, "w");
	if (!out) {
		PERROR("Failed to open log files: %s\n",
			outlog);
		return EN_DEFW_RC_LOG_CREATION_FAILURE;
	}

	if (defw_spawn_listener(&l_thread_id)) {
		PERROR("Failed to initialize listener thread");
		return EN_DEFW_RC_ERR_THREAD_STARTUP;
	}

	if (g_defw_cfg.shell == EN_DEFW_RUN_INTERACTIVE) {
		rc = python_run_interactive_shell();
		if (rc) {
			PERROR("Failed to run python interactively");
			defw_shutdown();
			return rc;
		}
		defw_shutdown();
	} else if(g_defw_cfg.shell == EN_DEFW_RUN_CMD_LINE &&
		  argc > 1) {
		rc = python_run_cmd_line(argc, argv);
		/* once Python is done execution of whatever was passed to
		 * it, it's assumed there is no longer a reason to keep
		 * the defw around
		 */
		defw_shutdown();
		return rc;
	}

	if (!g_defw_cfg.initialized) {
		PERROR("Python didn't initialize the system");
		defw_shutdown();
		return EN_DEFW_RC_ERR_THREAD_STARTUP;
	}

	pthread_join(l_thread_id, NULL);

	PDEBUG("%d: Exiting Framework\n", getpid());

	fclose(out);

	return EN_DEFW_RC_OK;
}

defw_rc_t defw_exec_py(char *py_code)
{
	return python_exec(py_code);
}

void defw_shutdown(void)
{
	defw_listener_shutdown();
	python_finalize();
}

