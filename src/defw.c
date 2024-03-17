#include "defw_sl.h"

int
main(int argc, char *argv[])
{
	defw_rc_t rc;

	rc = defw_start(argc, argv);

	switch (rc) {
	case EN_DEFW_RC_LOG_CREATION_FAILURE:
		return DEFW_EXIT_ERR_BAD_PARAM;
	default:
		return DEFW_EXIT_ERR_STARTUP;
	}

	return DEFW_EXIT_NORMAL;
}
