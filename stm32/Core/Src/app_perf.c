#include "app_perf.h"

#include <stddef.h>

#define BREATH_PERIOD_MS       4000U
#define BREATH_MIN_PERMILLE    10U
#define BREATH_MAX_PERMILLE    80U

#define INTRO_MS               30U
#define HOLD_PERMILLE          1000U

#define RELEASE_STAGE1_MS      500U
#define RELEASE_STAGE2_MS      1300U
#define RELEASE_TOTAL_MS       2500U
#define RELEASE_MID_PERMILLE   500U
#define RELEASE_LOW_PERMILLE   350U
#define RELEASE_END_PERMILLE   80U

#define EGG_FLASH_MS           1600U
#define EGG_TOTAL_MS           3600U
#define EGG_CYCLE_MS           200U
#define EGG_HALF_CYCLE_MS      100U

/* 0..1000, one full breathing cycle. index 0 = low, 32 = high. */
static const uint16_t k_breath_lut[64] =
{
    0, 2, 10, 22, 38, 59, 84, 113, 146, 183, 222, 264, 309, 355, 402, 451,
    500, 549, 598, 645, 691, 736, 778, 817, 854, 887, 916, 941, 962, 978,
    990, 998, 1000, 998, 990, 978, 962, 941, 916, 887, 854, 817, 778, 736,
    691, 645, 598, 549, 500, 451, 402, 355, 309, 264, 222, 183, 146, 113,
    84, 59, 38, 22, 10, 2
};

typedef struct
{
    perf_state_t state;
    uint32_t state_start_ms;
    uint16_t duty_permille;
    uint16_t intro_from;
    uint16_t release_from;
} glyph_runtime_t;

static glyph_runtime_t s_glyphs[GLYPH_COUNT];

static uint16_t breathing_duty(uint32_t elapsed_ms)
{
    uint32_t phase = (elapsed_ms % BREATH_PERIOD_MS) * 64U / BREATH_PERIOD_MS;
    uint32_t curve = k_breath_lut[phase];

    return (uint16_t)(BREATH_MIN_PERMILLE +
        ((BREATH_MAX_PERMILLE - BREATH_MIN_PERMILLE) * curve) / 1000U);
}

static uint16_t smoothstep_progress(uint32_t elapsed, uint32_t duration)
{
    if (duration == 0U || elapsed >= duration)
    {
        return 1000U;
    }

    uint32_t p = (elapsed * 1000U) / duration;
    uint32_t p2 = p * p;
    uint32_t value = (3U * p2 * 1000U - 2U * p2 * p) / 1000000U;

    return (uint16_t)value;
}

static uint16_t ease_out_progress(uint32_t elapsed, uint32_t duration)
{
    if (duration == 0U || elapsed >= duration)
    {
        return 1000U;
    }

    uint32_t inv = 1000U - (elapsed * 1000U) / duration;
    uint32_t value = 1000U - (((inv * inv) / 1000U) * inv) / 1000U;

    return (uint16_t)value;
}

static uint16_t release_duty(const glyph_runtime_t *runtime, uint32_t elapsed)
{
    uint16_t start = runtime->release_from;
    uint16_t stage1_end = (start > RELEASE_MID_PERMILLE)
                        ? RELEASE_MID_PERMILLE : start;
    uint16_t stage2_end = (stage1_end > RELEASE_LOW_PERMILLE)
                        ? RELEASE_LOW_PERMILLE : stage1_end;
    uint16_t stage3_end = (stage2_end > RELEASE_END_PERMILLE)
                        ? RELEASE_END_PERMILLE : stage2_end;

    if (elapsed < RELEASE_STAGE1_MS)
    {
        uint16_t p = ease_out_progress(elapsed, RELEASE_STAGE1_MS);
        return (uint16_t)(start - ((start - stage1_end) * p) / 1000U);
    }

    if (elapsed < RELEASE_STAGE2_MS)
    {
        uint16_t p = ease_out_progress(elapsed - RELEASE_STAGE1_MS,
                                       RELEASE_STAGE2_MS - RELEASE_STAGE1_MS);
        return (uint16_t)(stage1_end -
            ((stage1_end - stage2_end) * p) / 1000U);
    }

    uint32_t x = elapsed - RELEASE_STAGE2_MS;
    return (uint16_t)(stage2_end -
        ((stage2_end - stage3_end) * x) /
        (RELEASE_TOTAL_MS - RELEASE_STAGE2_MS));
}

static uint16_t tick_one(glyph_runtime_t *runtime, uint32_t now_ms)
{
    uint32_t elapsed = now_ms - runtime->state_start_ms;

    switch (runtime->state)
    {
    case PERF_STATE_OFF:
        return 0U;

    case PERF_STATE_STANDBY:
        return breathing_duty(elapsed);

    case PERF_STATE_INTRO:
    {
        if (elapsed >= INTRO_MS)
        {
            runtime->state = PERF_STATE_HOLD;
            runtime->state_start_ms = now_ms;
            return HOLD_PERMILLE;
        }

        uint16_t p = smoothstep_progress(elapsed, INTRO_MS);
        return (uint16_t)(runtime->intro_from +
            ((HOLD_PERMILLE - runtime->intro_from) * p) / 1000U);
    }

    case PERF_STATE_HOLD:
        return HOLD_PERMILLE;

    case PERF_STATE_RELEASE:
        if (elapsed >= RELEASE_TOTAL_MS)
        {
            runtime->state = PERF_STATE_STANDBY;
            /* Current Python behavior resumes breathing at its 8% high point. */
            runtime->state_start_ms = now_ms - (BREATH_PERIOD_MS / 2U);
            return breathing_duty(now_ms - runtime->state_start_ms);
        }
        return release_duty(runtime, elapsed);

    case PERF_STATE_EGG:
        if (elapsed < EGG_FLASH_MS)
        {
            uint32_t phase = elapsed % EGG_CYCLE_MS;
            return (phase < EGG_HALF_CYCLE_MS) ? 1000U : 0U;
        }
        if (elapsed < EGG_TOTAL_MS)
        {
            return 0U;
        }

        runtime->state = PERF_STATE_STANDBY;
        runtime->state_start_ms = now_ms;
        return breathing_duty(0U);

    default:
        return 0U;
    }
}

static bool apply_one(glyph_runtime_t *runtime, perf_action_t action,
                      uint32_t now_ms)
{
    switch (action)
    {
    case PERF_ACTION_STANDBY:
        if (runtime->state == PERF_STATE_EGG)
        {
            return false;
        }
        runtime->state = PERF_STATE_STANDBY;
        runtime->state_start_ms = now_ms;
        return true;

    case PERF_ACTION_GATE:
        if (runtime->state == PERF_STATE_EGG)
        {
            return false;
        }
        runtime->intro_from = runtime->duty_permille;
        runtime->state = PERF_STATE_INTRO;
        runtime->state_start_ms = now_ms;
        return true;

    case PERF_ACTION_RELEASE:
        if (runtime->state == PERF_STATE_EGG)
        {
            return false;
        }
        runtime->release_from = runtime->duty_permille;
        runtime->state = PERF_STATE_RELEASE;
        runtime->state_start_ms = now_ms;
        return true;

    case PERF_ACTION_EGG:
        runtime->state = PERF_STATE_EGG;
        runtime->state_start_ms = now_ms;
        runtime->duty_permille = 0U;
        return true;

    case PERF_ACTION_OFF:
        runtime->state = PERF_STATE_OFF;
        runtime->duty_permille = 0U;
        return true;

    default:
        return false;
    }
}

void app_perf_init(uint32_t now_ms)
{
    (void)now_ms;

    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        s_glyphs[i].state = PERF_STATE_OFF;
        s_glyphs[i].state_start_ms = 0U;
        s_glyphs[i].duty_permille = 0U;
        s_glyphs[i].intro_from = 0U;
        s_glyphs[i].release_from = 0U;
    }

    board_pwm_all_off();
}

void app_perf_tick(uint32_t now_ms)
{
    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        uint16_t duty = tick_one(&s_glyphs[i], now_ms);
        s_glyphs[i].duty_permille = duty;
        board_pwm_set_duty(g_glyph_map[i].pwm_id, duty);
    }
}

bool app_perf_apply(uint32_t glyph_mask, perf_action_t action,
                    uint8_t profile_id, uint16_t value, uint32_t now_ms)
{
    bool applied = false;

    (void)profile_id;
    (void)value;

    if ((glyph_mask & ~((uint32_t)GLYPH_ALL_MASK)) != 0U ||
        glyph_mask == 0U)
    {
        return false;
    }

    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        if ((glyph_mask & GLYPH_BIT(i)) == 0U)
        {
            continue;
        }

        if (apply_one(&s_glyphs[i], action, now_ms))
        {
            applied = true;
        }
    }

    return applied;
}

void app_perf_all_off(void)
{
    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        s_glyphs[i].state = PERF_STATE_OFF;
        s_glyphs[i].state_start_ms = 0U;
        s_glyphs[i].duty_permille = 0U;
    }

    board_pwm_all_off();
}

uint32_t app_perf_active_mask(void)
{
    uint32_t mask = 0U;

    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        if (s_glyphs[i].state == PERF_STATE_INTRO ||
            s_glyphs[i].state == PERF_STATE_HOLD ||
            s_glyphs[i].state == PERF_STATE_RELEASE ||
            s_glyphs[i].state == PERF_STATE_EGG)
        {
            mask |= GLYPH_BIT(i);
        }
    }

    return mask;
}

uint8_t app_perf_get_state(glyph_id_t glyph)
{
    if ((uint32_t)glyph >= (uint32_t)GLYPH_COUNT)
    {
        return (uint8_t)PERF_STATE_OFF;
    }

    return (uint8_t)s_glyphs[glyph].state;
}

uint16_t app_perf_get_duty(glyph_id_t glyph)
{
    if ((uint32_t)glyph >= (uint32_t)GLYPH_COUNT)
    {
        return 0U;
    }

    return s_glyphs[glyph].duty_permille;
}
