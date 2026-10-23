#pragma once
// A press of + or - that did not open the pause menu, and why
// (GameScenePauseControl.cpp): one line in pause-log.txt in the user
// directory, for players whose pause "does not work". Plain C.

#ifdef __cplusplus
extern "C" {
#endif

/* Appends one line (without its newline), with the local time, to
 * <user>/pause-log.txt and stderr. Game thread. */
void petari_host_pause_log(const char* line);

#ifdef __cplusplus
}
#endif
