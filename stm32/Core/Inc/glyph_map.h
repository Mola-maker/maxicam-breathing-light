#ifndef GLYPH_MAP_H
#define GLYPH_MAP_H

#ifdef __cplusplus
extern "C" {
#endif

#include "board_pwm.h"

#include <stdint.h>

/* Chinese text is for logs only. The protocol and the performance engine use
 * stable numeric glyph IDs and bit masks. */
#define GLYPH_TABLE(X) \
    X(GLYPH_CHANG, "长", BOARD_PWM_PWM1) \
    X(GLYPH_CHUN,  "春", BOARD_PWM_PWM2) \
    X(GLYPH_ALL_LAMPS, "全灯", BOARD_PWM_PWM1)

typedef enum
{
#define GLYPH_ENUM_ROW(id, text_, pwm_id_) id,
    GLYPH_TABLE(GLYPH_ENUM_ROW)
#undef GLYPH_ENUM_ROW
    GLYPH_COUNT
} glyph_id_t;

typedef struct
{
    const char *text;
    board_pwm_id_t pwm_id;
} glyph_map_t;

extern const glyph_map_t g_glyph_map[GLYPH_COUNT];

#define GLYPH_BIT(id) (1UL << (uint32_t)(id))
#define GLYPH_ALL_MASK ((1UL << (uint32_t)GLYPH_COUNT) - 1UL)

/* Current single-word "长春" performance targets both character boards. */
#define WORD_CHANGCHUN_MASK \
    (GLYPH_BIT(GLYPH_CHANG) | GLYPH_BIT(GLYPH_CHUN))

/* Test-only group: all 13 lamp outputs, never HEAT1/HEAT2. */
#define ALL_LAMPS_MASK GLYPH_BIT(GLYPH_ALL_LAMPS)

#ifdef __cplusplus
}
#endif

#endif /* GLYPH_MAP_H */
