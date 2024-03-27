#ifndef DEFW_PRINT_H
#define DEFW_PRINT_H

#include <stdarg.h>
#include <stdbool.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pthread.h>
#include "defw_common.h"

#define OUT_LOG_NAME "defw_out.log"
#define OUT_PY_LOG "defw_py.log"
#define LARGE_LOG_FILE 400000000 /* 400 MB */

static FILE *out;
static char *outlog;
static pthread_spinlock_t log_spin_lock;
static defw_log_level_t g_logger_level;

static inline void logger_level(defw_log_level_t level)
{
	g_logger_level = level;
}

static inline void defw_init_logging(void)
{
	pthread_spin_init(&log_spin_lock, PTHREAD_PROCESS_PRIVATE);
}

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

	if (g_logger_level == EN_LOG_LEVEL_MSG &&
	    loglevel != EN_LOG_LEVEL_MSG)
		return;

	if (g_logger_level < loglevel)
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

#endif /* DEFW_PRINT_H */
