#include "glyph_map.h"

const glyph_map_t g_glyph_map[GLYPH_COUNT] =
{
#define GLYPH_ROW(id, text_, pwm_id_) [id] = { text_, pwm_id_ },
    GLYPH_TABLE(GLYPH_ROW)
#undef GLYPH_ROW
};

_Static_assert(GLYPH_COUNT <= 32, "glyph_mask is a 32-bit bitmask");
