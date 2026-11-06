#ifndef APP_PERF_H
#define APP_PERF_H

#ifdef __cplusplus
extern "C" {
#endif

#include "glyph_map.h"

#include <stdbool.h>
#include <stdint.h>

typedef enum
{
    PERF_ACTION_STANDBY = 0,
    PERF_ACTION_GATE = 1,
    PERF_ACTION_RELEASE = 2,
    PERF_ACTION_EGG = 3,
    PERF_ACTION_OFF = 4
} perf_action_t;

typedef enum
{
    PERF_STATE_OFF = 0,
    PERF_STATE_STANDBY,
    PERF_STATE_INTRO,
    PERF_STATE_HOLD,
    PERF_STATE_RELEASE,
    PERF_STATE_EGG
} perf_state_t;

void app_perf_init(uint32_t now_ms);
void app_perf_tick(uint32_t now_ms);
bool app_perf_apply(uint32_t glyph_mask, perf_action_t action,
                    uint8_t profile_id, uint16_t value, uint32_t now_ms);
void app_perf_all_off(void);
uint32_t app_perf_active_mask(void);
uint8_t app_perf_get_state(glyph_id_t glyph);
uint16_t app_perf_get_duty(glyph_id_t glyph);

#ifdef __cplusplus
}
#endif

#endif /* APP_PERF_H */
