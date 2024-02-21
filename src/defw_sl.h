#ifndef IFW_ISL_H
#define IFW_ISL_H

#include <stdbool.h>
#include "defw_common.h"

defw_rc_t defw_start(int argc, char *argv[], bool daemon);
void defw_shutdown(void);
defw_rc_t defw_exec_py(char *py_code);

#endif /* IFW_ISL_H */
