#ifndef DEFW_H
#define DEFW_H

#include <stdbool.h>
#include <stdio.h>
#include <stdarg.h>
#include <time.h>
#include <sys/stat.h>
#include <uuid/uuid.h>
#include <unistd.h>
#include <pthread.h>
#include "defw_common.h"
#include "defw_agent.h"
#include "defw_message.h"

extern FILE *out;
extern char *outlog;
extern pthread_spinlock_t log_spin_lock;

#define OUT_LOG_NAME "defw_out.log"
#define OUT_PY_LOG "defw_py.log"
#define LARGE_LOG_FILE 400000000 /* 400 MB */
#define DEFW_UUID_STR_LEN		(UUID_STR_LEN+12)

typedef struct hb_info_s {
	struct sockaddr_in parent_address;
	int agent_telnet_port;
	char node_name[MAX_STR_LEN];
} hb_info_t;

typedef struct defw_listener_info_s {
	defw_type_t type;
	struct sockaddr_in listen_address;
	hb_info_t hb_info;
} defw_listener_info_t;

typedef struct defw_config_params_s {
	bool initialized;
	bool in_daemon_mode;
	defw_listener_info_t l_info;
	uuid_t uuid;
	defw_run_mode_t shell; /* run in [non]-interactive or daemon mode */
	char cfg_path[MAX_STR_LEN]; /* path to config file */
	char defw_path[MAX_STR_LEN]; /* path to defw */
	char py_path[MAX_STR_LEN]; /* other python specific paths */
	char parent_name[MAX_STR_LEN]; /* name of master. Important if I'm an agent */
	char parent_hostname[MAX_STR_LEN]; /* hostname of master. Important if I'm an agent */
	char hostname[MAX_STR_LEN]; /* local hostname. */
	char suite[MAX_STR_LEN]; /* name of suite to run. Run all if not present */
	char suite_list[MAX_STR_LEN]; /* list of suites to run. Takes precedence
			     over single suite parameter */
	char script[MAX_STR_LEN]; /* name of script to run. Suite must be specified */
	char pattern[MAX_STR_LEN]; /* file match pattern */
	char results_file[MAX_STR_LEN]; /* path to results file */
	char tmp_dir[MAX_STR_LEN]; /* directory to put temporary files */
	char *agents[MAX_NUM_AGENTS]; /* list of agents to wait for before
			       * starting the test
			       */
	int loglevel;
} defw_config_params_t;

extern defw_config_params_t g_defw_cfg;

static inline void defw_log_print(int loglevel, bool error, char *color1,
				 char *color2, char *file, int line,
				 char *fmt, ...)
{
	time_t debugnow;
	int di;
	char debugtimestr[30];
	struct stat st;
	va_list args;
	FILE *print = stderr;

	if (g_defw_cfg.loglevel == EN_LOG_LEVEL_MSG &&
	    loglevel != EN_LOG_LEVEL_MSG)
		return;

	if (g_defw_cfg.loglevel < loglevel)
		return;

	if (!outlog || !out)
		goto print_err;

	/* check if the log file has grown too large */
	print = out;
	stat(outlog, &st);
	if (st.st_size > LARGE_LOG_FILE)
		out = freopen(outlog, "w", out);

print_err:
	time(&debugnow);
	ctime_r(&debugnow, debugtimestr);
	for (di = 0; di < 30; di++) {
		if (debugtimestr[di] == '\n')
			debugtimestr[di] = '\0';
	}

	pthread_spin_lock(&log_spin_lock);
	fprintf(print, "%s%lu %s %s:%s:%d " RESET "%s- ", color1,
		pthread_self(), (error) ? "ERROR" : "", debugtimestr, file, line, color2);
	va_start(args, fmt);
	vfprintf(print, fmt, args);
	va_end(args);
	fprintf(print, RESET"\n");
	fflush(print);
	pthread_spin_unlock(&log_spin_lock);
}

#define PERROR(fmt, args...) defw_log_print(EN_LOG_LEVEL_ERROR, true, BOLDRED, RED, __FILE__, __LINE__, fmt, ## args)
#define PDEBUG(fmt, args...) defw_log_print(EN_LOG_LEVEL_DEBUG, false, BOLDGREEN, GREEN, __FILE__, __LINE__, fmt, ## args)
#define PMSG(fmt, args...) defw_log_print(EN_LOG_LEVEL_MSG, false, BOLDMAGENTA, BOLDBLUE, __FILE__, __LINE__, fmt, ## args)

int establishTCPConnection(unsigned long uiAddress,
			   int iPort,
			   bool b_non_block,
			   bool endian);


defw_rc_t sendTcpMessage(int iTcpSocket, char *pcBody, int iBodySize);

defw_rc_t defw_send_msg(int fd, char *msg, size_t msg_size,
			defw_msg_type_t type);

defw_rc_t populateMsgHdr(int rsocket, char *msg_hdr,
			 int msg_type, int msg_size,
			 int defw_version_number);

defw_rc_t readTcpMessage(int iFd, char *pcBuffer,
			int iBufferSize, int iTimeout,
			bool force_wait);

defw_rc_t closeTcpConnection(int iTcpSocket);

#endif /* DEFW_H */
