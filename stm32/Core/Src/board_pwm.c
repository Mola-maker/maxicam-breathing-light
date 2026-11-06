#include "board_pwm.h"

#include <stddef.h>

/* Logical board outputs. Keep this table as the only place where a PWM
 * header name is tied to a timer/channel. */
#define BOARD_PWM_TABLE(X) \
    X(BOARD_PWM_PWM1,  "PWM1",  &htim2, TIM_CHANNEL_1, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM2,  "PWM2",  &htim2, TIM_CHANNEL_2, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM3,  "PWM3",  &htim2, TIM_CHANNEL_3, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM4,  "PWM4",  &htim2, TIM_CHANNEL_4, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM5,  "PWM5",  &htim3, TIM_CHANNEL_3, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM6,  "PWM6",  &htim3, TIM_CHANNEL_4, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM7,  "PWM7",  &htim1, TIM_CHANNEL_1, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM8,  "PWM8",  &htim1, TIM_CHANNEL_2, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM9,  "PWM9",  &htim1, TIM_CHANNEL_3, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM10, "PWM10", &htim1, TIM_CHANNEL_4, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM11, "PWM11", &htim4, TIM_CHANNEL_1, PWM_FREQ_20K) \
    X(BOARD_PWM_PWM12, "PWM12", &htim3, TIM_CHANNEL_2, PWM_FREQ_2K) \
    X(BOARD_PWM_PWM13, "PWM13", &htim3, TIM_CHANNEL_1, PWM_FREQ_2K) \
    X(BOARD_PWM_HEAT1, "HEAT1", &htim4, TIM_CHANNEL_3, PWM_FREQ_20K) \
    X(BOARD_PWM_HEAT2, "HEAT2", &htim4, TIM_CHANNEL_2, PWM_FREQ_20K)

const board_pwm_map_t g_board_pwm_map[BOARD_PWM_COUNT] =
{
#define BOARD_PWM_ROW(id, name_, htim_, channel_, freq_) \
    [id] = { name_, htim_, channel_, freq_ },
    BOARD_PWM_TABLE(BOARD_PWM_ROW)
#undef BOARD_PWM_ROW
};

_Static_assert(BOARD_PWM_COUNT == 15, "board PWM table must contain 15 outputs");

static uint32_t duty_to_ccr(const board_pwm_map_t *map, uint16_t duty_permille)
{
    uint32_t duty = duty_permille;

    if (duty > 1000U)
    {
        duty = 1000U;
    }

    if (map->freq_class == PWM_FREQ_2K)
    {
        return duty;
    }

    return (duty * 400U + 500U) / 1000U;
}

void board_pwm_init(void)
{
    for (uint32_t i = 0; i < (uint32_t)BOARD_PWM_COUNT; i++)
    {
        const board_pwm_map_t *map = &g_board_pwm_map[i];

        __HAL_TIM_SET_COMPARE(map->htim, map->channel, 0U);

        if (HAL_TIM_PWM_Start(map->htim, map->channel) != HAL_OK)
        {
            Error_Handler();
        }
    }
}

void board_pwm_set_duty(board_pwm_id_t id, uint16_t duty_permille)
{
    if ((uint32_t)id >= (uint32_t)BOARD_PWM_COUNT)
    {
        return;
    }

    const board_pwm_map_t *map = &g_board_pwm_map[id];
    __HAL_TIM_SET_COMPARE(map->htim, map->channel,
                          duty_to_ccr(map, duty_permille));
}

void board_pwm_all_off(void)
{
    for (uint32_t i = 0; i < (uint32_t)BOARD_PWM_COUNT; i++)
    {
        const board_pwm_map_t *map = &g_board_pwm_map[i];
        __HAL_TIM_SET_COMPARE(map->htim, map->channel, 0U);
    }
}
