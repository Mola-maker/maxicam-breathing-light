#ifndef BOARD_PWM_H
#define BOARD_PWM_H

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"
#include "tim.h"

#include <stdint.h>

typedef enum
{
    PWM_FREQ_2K = 0,
    PWM_FREQ_20K
} pwm_freq_class_t;

typedef enum
{
    BOARD_PWM_PWM1 = 0,
    BOARD_PWM_PWM2,
    BOARD_PWM_PWM3,
    BOARD_PWM_PWM4,
    BOARD_PWM_PWM5,
    BOARD_PWM_PWM6,
    BOARD_PWM_PWM7,
    BOARD_PWM_PWM8,
    BOARD_PWM_PWM9,
    BOARD_PWM_PWM10,
    BOARD_PWM_PWM11,
    BOARD_PWM_PWM12,
    BOARD_PWM_PWM13,
    BOARD_PWM_HEAT1,
    BOARD_PWM_HEAT2,
    BOARD_PWM_COUNT
} board_pwm_id_t;

typedef struct
{
    const char *name;
    TIM_HandleTypeDef *htim;
    uint32_t channel;
    pwm_freq_class_t freq_class;
} board_pwm_map_t;

extern const board_pwm_map_t g_board_pwm_map[BOARD_PWM_COUNT];

void board_pwm_init(void);
void board_pwm_set_duty(board_pwm_id_t id, uint16_t duty_permille);
void board_pwm_all_off(void);

#ifdef __cplusplus
}
#endif

#endif /* BOARD_PWM_H */
