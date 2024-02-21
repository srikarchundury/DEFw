#ifndef IFW_LISTENER_H
#define IFW_LISTENER_H

#include "defw_common.h"
#include "defw_agent.h"

defw_rc_t defw_spawn_listener(pthread_t *id);

void defw_listener_shutdown(void);

int defw_get_highest_fd(void);

#endif /* IFW_LISTENER_H */
