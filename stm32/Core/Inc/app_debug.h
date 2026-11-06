#ifndef APP_DEBUG_H
#define APP_DEBUG_H

#ifdef __cplusplus
extern "C" {
#endif

void app_debug_init(void);
void app_debug_printf(const char *format, ...);

#ifdef __cplusplus
}
#endif

#endif /* APP_DEBUG_H */
