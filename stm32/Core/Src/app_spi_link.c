#include "app_spi_link.h"

#include "app_debug.h"
#include "app_perf.h"
#include "board_pwm.h"
#include "glyph_map.h"
#include "main.h"
#include "spi.h"

#include <string.h>

#define APP_SPI_MAX_PAYLOAD       44U
#define APP_SPI_LINK_TIMEOUT_MS   500U
#define APP_SPI_ARM_TIMEOUT_MS    500U
#define APP_SPI_TEMP_MAX_AGE_MS   3000U

#define FRAME_MAGIC_0             0x5AU
#define FRAME_MAGIC_1             0xA5U
#define FRAME_TYPE_CONTROL        0x01U
#define FRAME_TYPE_STATUS         0x81U

#define TLV_HELLO                 0x01U
#define TLV_TEMP                  0x02U
#define TLV_PERFORM               0x10U
#define TLV_HEARTBEAT             0x20U
#define TLV_THERMAL_CONFIG        0x30U
#define TLV_ALL_OFF               0x7FU

#define TLV_STATUS                0x81U
#define TLV_CAPS                  0x82U

#define FEATURE_PERFORM           (1UL << 0)
#define FEATURE_TEMP              (1UL << 1)
#define FEATURE_HEARTBEAT         (1UL << 2)
#define FEATURE_EGG               (1UL << 3)
#define FEATURE_THERMAL_PID       (1UL << 4)
#define FEATURE_DIRECT            (1UL << 5)

#define FAULT_CRC                 (1U << 0)
#define FAULT_FORMAT              (1U << 1)
#define FAULT_SPI                 (1U << 2)
#define FAULT_UNKNOWN_TLV         (1U << 3)
#define FAULT_NEED_HELLO          (1U << 4)
#define FAULT_TEMP_STALE          (1U << 5)
#define FAULT_TEMP_INVALID        (1U << 6)
#define FAULT_HEATER_UNSUPPORTED  (1U << 7)
#define FAULT_BAD_MASK            (1U << 8)
#define FAULT_PROTOCOL            (1U << 9)
#define FAULT_LINK_LOST           (1U << 10)

static uint8_t s_tx_frame[APP_SPI_FRAME_SIZE];
static uint8_t s_rx_frame[APP_SPI_FRAME_SIZE];
static uint8_t s_pending_rx[APP_SPI_FRAME_SIZE];

static volatile bool s_frame_pending;
static volatile bool s_spi_armed;
static uint32_t s_arm_tick_ms;

static uint32_t s_tx_seq;
static uint32_t s_session_id;
static uint32_t s_last_control_seq;
static uint32_t s_last_event_seq;
static bool s_have_control_seq;
static bool s_have_event_seq;
static bool s_session_active;
static bool s_need_hello;
static bool s_rx_seen;
static uint32_t s_last_valid_rx_ms;
static app_spi_link_state_t s_link_state;
static volatile uint16_t s_faults;

static uint16_t s_heartbeat_ms;
static uint32_t s_host_features;

static bool s_temp_seen;
static int32_t s_temp_mc;
static uint16_t s_temp_sample_seq;
static uint32_t s_temp_sample_tick_ms;
static bool s_temp_valid;
static uint8_t s_temp_source;

static uint32_t s_last_error_log_ms;

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] |
           ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

static void wr16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)(value & 0xFFU);
    p[1] = (uint8_t)((value >> 8) & 0xFFU);
}

static void wr32(uint8_t *p, uint32_t value)
{
    p[0] = (uint8_t)(value & 0xFFU);
    p[1] = (uint8_t)((value >> 8) & 0xFFU);
    p[2] = (uint8_t)((value >> 16) & 0xFFU);
    p[3] = (uint8_t)((value >> 24) & 0xFFU);
}

static uint16_t crc16_ccitt(const uint8_t *data, uint32_t length)
{
    uint16_t crc = 0xFFFFU;

    for (uint32_t i = 0; i < length; i++)
    {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (uint32_t bit = 0; bit < 8U; bit++)
        {
            if ((crc & 0x8000U) != 0U)
            {
                crc = (uint16_t)((crc << 1) ^ 0x1021U);
            }
            else
            {
                crc = (uint16_t)(crc << 1);
            }
        }
    }

    return crc;
}

static void frame_begin(uint8_t *frame, uint8_t type, uint32_t seq,
                        uint32_t session_id, uint16_t payload_len)
{
    memset(frame, 0, APP_SPI_FRAME_SIZE);
    frame[0] = FRAME_MAGIC_0;
    frame[1] = FRAME_MAGIC_1;
    frame[2] = APP_SPI_PROTOCOL_VERSION;
    frame[3] = type;
    wr32(&frame[4], seq);
    wr32(&frame[8], session_id);
    wr16(&frame[12], payload_len);
    wr16(&frame[14], 0U);
}

static void frame_finish(uint8_t *frame)
{
    wr16(&frame[60], crc16_ccitt(frame, 60U));
    wr16(&frame[62], 0U);
}

static uint16_t append_tlv(uint8_t *payload, uint16_t offset, uint8_t type,
                           const uint8_t *value, uint8_t length)
{
    if ((uint32_t)offset + 2U + length > APP_SPI_MAX_PAYLOAD)
    {
        return offset;
    }

    payload[offset++] = type;
    payload[offset++] = length;
    memcpy(&payload[offset], value, length);
    return (uint16_t)(offset + length);
}

static bool seq_is_new(uint32_t seq)
{
    if (!s_have_control_seq)
    {
        return true;
    }

    return (int32_t)(seq - s_last_control_seq) > 0;
}

static void reset_session(uint32_t session_id, uint32_t now_ms)
{
    (void)now_ms;

    s_session_id = session_id;
    s_session_active = false;
    s_need_hello = true;
    s_have_control_seq = false;
    s_last_control_seq = 0U;
    s_have_event_seq = false;
    s_last_event_seq = 0U;
    s_link_state = APP_SPI_LINK_WAIT_HELLO;
    s_faults &= (uint16_t)~(FAULT_NEED_HELLO | FAULT_LINK_LOST);
    app_perf_all_off();

    app_debug_printf("[spi] new session 0x%08lX, waiting HELLO\r\n",
                     (unsigned long)session_id);
}

static void handle_hello(const uint8_t *value, uint8_t length)
{
    if (length != 8U)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    uint8_t protocol_min = value[0];
    uint8_t protocol_max = value[1];

    if (protocol_min > APP_SPI_PROTOCOL_VERSION ||
        protocol_max < APP_SPI_PROTOCOL_VERSION)
    {
        s_faults |= FAULT_PROTOCOL;
        s_link_state = APP_SPI_LINK_FAULT;
        app_perf_all_off();
        return;
    }

    s_heartbeat_ms = rd16(&value[2]);
    if (s_heartbeat_ms < 100U)
    {
        s_heartbeat_ms = 100U;
    }
    s_host_features = rd32(&value[4]);

    s_session_active = true;
    s_need_hello = false;
    s_link_state = APP_SPI_LINK_ACTIVE;
    s_faults &= (uint16_t)~(FAULT_NEED_HELLO | FAULT_LINK_LOST |
                            FAULT_PROTOCOL);
    app_perf_all_off();

    app_debug_printf("[spi] HELLO ok, heartbeat=%ums features=0x%08lX\r\n",
                     (unsigned int)s_heartbeat_ms,
                     (unsigned long)s_host_features);
}

static void handle_temp(const uint8_t *value, uint8_t length, uint32_t now_ms)
{
    if (length != 10U)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    int32_t temp_mc = (int32_t)rd32(&value[0]);
    uint16_t sample_seq = rd16(&value[4]);
    uint16_t age_ms = rd16(&value[6]);
    bool valid = (value[8] != 0U);
    uint8_t source = value[9];

    if (temp_mc < -100000 || temp_mc > 150000)
    {
        valid = false;
    }

    s_temp_seen = true;
    s_temp_mc = temp_mc;
    s_temp_sample_seq = sample_seq;
    s_temp_source = source;
    s_temp_valid = valid;
    s_temp_sample_tick_ms = now_ms - age_ms;

    if (valid)
    {
        s_faults &= (uint16_t)~FAULT_TEMP_INVALID;
    }
    else
    {
        s_faults |= FAULT_TEMP_INVALID;
    }
}

static void handle_perform(const uint8_t *value, uint8_t length,
                           uint32_t now_ms)
{
    if (length != 12U)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    if (!s_session_active)
    {
        s_need_hello = true;
        s_faults |= FAULT_NEED_HELLO;
        return;
    }

    uint32_t glyph_mask = rd32(&value[0]);
    uint8_t action = value[4];
    uint8_t profile_id = value[5];
    uint32_t event_seq = rd32(&value[6]);
    uint16_t event_value = rd16(&value[10]);

    if (glyph_mask == 0U ||
        (glyph_mask & ~((uint32_t)GLYPH_ALL_MASK)) != 0U)
    {
        s_faults |= FAULT_BAD_MASK;
        return;
    }

    if (action > (uint8_t)PERF_ACTION_OFF)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    if (s_have_event_seq &&
        (int32_t)(event_seq - s_last_event_seq) <= 0)
    {
        return;
    }

    (void)app_perf_apply(glyph_mask, (perf_action_t)action, profile_id,
                         event_value, now_ms);
    s_last_event_seq = event_seq;
    s_have_event_seq = true;

    app_debug_printf("[spi] PERFORM mask=0x%lX action=%u event=%lu\r\n",
                     (unsigned long)glyph_mask,
                     (unsigned int)action,
                     (unsigned long)event_seq);
}

static void process_tlvs(const uint8_t *payload, uint16_t payload_len,
                         uint32_t now_ms)
{
    uint16_t offset = 0U;

    while ((uint32_t)offset + 2U <= payload_len)
    {
        uint8_t type = payload[offset++];
        uint8_t length = payload[offset++];

        if ((uint32_t)offset + length > payload_len)
        {
            s_faults |= FAULT_FORMAT;
            return;
        }

        const uint8_t *value = &payload[offset];

        switch (type)
        {
        case TLV_HELLO:
            handle_hello(value, length);
            break;

        case TLV_TEMP:
            handle_temp(value, length, now_ms);
            break;

        case TLV_PERFORM:
            handle_perform(value, length, now_ms);
            break;

        case TLV_HEARTBEAT:
            if (length != 8U)
            {
                s_faults |= FAULT_FORMAT;
            }
            break;

        case TLV_ALL_OFF:
            app_perf_all_off();
            app_debug_printf("[spi] ALL_OFF\r\n");
            break;

        case TLV_THERMAL_CONFIG:
            /* v1 intentionally does not drive HEAT1/HEAT2. */
            s_faults |= FAULT_HEATER_UNSUPPORTED;
            break;

        default:
            s_faults |= FAULT_UNKNOWN_TLV;
            break;
        }

        offset = (uint16_t)(offset + length);
    }

    if (offset != payload_len)
    {
        s_faults |= FAULT_FORMAT;
    }
}

static void process_control_frame(const uint8_t *frame, uint32_t now_ms)
{
    if (frame[0] != FRAME_MAGIC_0 ||
        frame[1] != FRAME_MAGIC_1 ||
        frame[2] != APP_SPI_PROTOCOL_VERSION ||
        frame[3] != FRAME_TYPE_CONTROL)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    uint16_t payload_len = rd16(&frame[12]);
    if (payload_len > APP_SPI_MAX_PAYLOAD)
    {
        s_faults |= FAULT_FORMAT;
        return;
    }

    uint16_t expected_crc = crc16_ccitt(frame, 60U);
    if (rd16(&frame[60]) != expected_crc)
    {
        s_faults |= FAULT_CRC;
        if ((now_ms - s_last_error_log_ms) >= 1000U)
        {
            s_last_error_log_ms = now_ms;
            app_debug_printf("[spi] CRC error\r\n");
        }
        return;
    }

    uint32_t seq = rd32(&frame[4]);
    uint32_t session_id = rd32(&frame[8]);

    if (session_id != s_session_id)
    {
        reset_session(session_id, now_ms);
    }

    if (!s_rx_seen || !s_session_active || seq_is_new(seq))
    {
        s_last_control_seq = seq;
        s_have_control_seq = true;
        s_rx_seen = true;
        s_last_valid_rx_ms = now_ms;
        process_tlvs(&frame[16], payload_len, now_ms);
    }
    else
    {
        /* Duplicate request: refresh link health but do not execute it again. */
        s_rx_seen = true;
        s_last_valid_rx_ms = now_ms;
    }

    if (!s_session_active && s_link_state == APP_SPI_LINK_BOOT)
    {
        s_link_state = APP_SPI_LINK_WAIT_HELLO;
    }
}

static void build_status_frame(uint32_t now_ms)
{
    uint8_t payload[APP_SPI_MAX_PAYLOAD];
    uint8_t status[29U + GLYPH_COUNT];
    uint8_t caps[8];
    uint16_t offset = 0U;
    uint16_t age_ms = 0xFFFFU;
    bool temp_valid = false;
    uint16_t fault_flags = s_faults;

    if (s_temp_seen)
    {
        uint32_t age = now_ms - s_temp_sample_tick_ms;
        age_ms = (age > 0xFFFFU) ? 0xFFFFU : (uint16_t)age;
        temp_valid = s_temp_valid && (age <= APP_SPI_TEMP_MAX_AGE_MS);
        if (!temp_valid)
        {
            fault_flags |= FAULT_TEMP_STALE;
        }
    }

    if (s_need_hello)
    {
        fault_flags |= FAULT_NEED_HELLO;
    }

    wr32(&status[0], s_last_control_seq);
    wr32(&status[4], s_last_event_seq);
    wr32(&status[8], app_perf_active_mask());
    wr32(&status[12], now_ms);
    wr16(&status[16], fault_flags);
    wr32(&status[18], (uint32_t)s_temp_mc);
    wr16(&status[22], age_ms);
    status[24] = temp_valid ? 1U : 0U;
    status[25] = (uint8_t)s_link_state;
    wr16(&status[26], s_temp_sample_seq);
    status[28] = s_temp_source;

    for (uint32_t i = 0; i < (uint32_t)GLYPH_COUNT; i++)
    {
        status[29U + i] = app_perf_get_state((glyph_id_t)i);
    }

    offset = append_tlv(payload, offset, TLV_STATUS, status,
                        (uint8_t)sizeof(status));

    caps[0] = APP_SPI_PROTOCOL_VERSION;
    caps[1] = (uint8_t)GLYPH_COUNT;
    caps[2] = (uint8_t)BOARD_PWM_COUNT;
    caps[3] = 0U;
    wr32(&caps[4], FEATURE_PERFORM | FEATURE_TEMP |
                   FEATURE_HEARTBEAT | FEATURE_EGG);
    offset = append_tlv(payload, offset, TLV_CAPS, caps, sizeof(caps));

    frame_begin(s_tx_frame, FRAME_TYPE_STATUS, s_tx_seq++, s_session_id, offset);
    memcpy(&s_tx_frame[16], payload, offset);
    frame_finish(s_tx_frame);
}

static void arm_spi(void)
{
    if (s_spi_armed || s_frame_pending)
    {
        return;
    }

    if (HAL_SPI_TransmitReceive_IT(&hspi1, s_tx_frame, s_rx_frame,
                                   APP_SPI_FRAME_SIZE) == HAL_OK)
    {
        s_spi_armed = true;
        s_arm_tick_ms = HAL_GetTick();
    }
    else
    {
        s_spi_armed = false;
        s_faults |= FAULT_SPI;
    }
}

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
    if (hspi->Instance == SPI1)
    {
        memcpy(s_pending_rx, s_rx_frame, APP_SPI_FRAME_SIZE);
        s_spi_armed = false;
        s_frame_pending = true;
    }
}

void HAL_SPI_ErrorCallback(SPI_HandleTypeDef *hspi)
{
    if (hspi->Instance == SPI1)
    {
        s_spi_armed = false;
        s_faults |= FAULT_SPI;
    }
}

void app_spi_link_init(uint32_t now_ms)
{
    s_tx_seq = 1U;
    s_session_id = 0U;
    s_last_control_seq = 0U;
    s_last_event_seq = 0U;
    s_have_control_seq = false;
    s_have_event_seq = false;
    s_session_active = false;
    s_need_hello = true;
    s_rx_seen = false;
    s_last_valid_rx_ms = now_ms;
    s_link_state = APP_SPI_LINK_BOOT;
    s_faults = 0U;
    s_heartbeat_ms = 1000U;
    s_host_features = 0U;
    s_temp_seen = false;
    s_temp_mc = 0;
    s_temp_sample_seq = 0U;
    s_temp_sample_tick_ms = now_ms;
    s_temp_valid = false;
    s_temp_source = 0xFFU;
    s_last_error_log_ms = now_ms;

    s_frame_pending = false;
    s_spi_armed = false;

    /* Keep CS deasserted if the host is disconnected. */
    GPIO_InitTypeDef cs_pin = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE();
    cs_pin.Pin = GPIO_PIN_4;
    cs_pin.Mode = GPIO_MODE_INPUT;
    cs_pin.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(GPIOA, &cs_pin);

    HAL_NVIC_SetPriority(SPI1_IRQn, 1U, 0U);
    HAL_NVIC_EnableIRQ(SPI1_IRQn);

    build_status_frame(now_ms);
    arm_spi();

    app_debug_printf("[spi] slave armed, frame=%u bytes\r\n",
                     (unsigned int)APP_SPI_FRAME_SIZE);
}

void app_spi_link_poll(uint32_t now_ms)
{
    if (s_frame_pending)
    {
        s_frame_pending = false;
        process_control_frame(s_pending_rx, now_ms);
        build_status_frame(now_ms);
        arm_spi();
    }
    else if (!s_spi_armed)
    {
        if (hspi1.State != HAL_SPI_STATE_READY)
        {
            (void)HAL_SPI_Abort(&hspi1);
        }
        build_status_frame(now_ms);
        arm_spi();
    }

    if (s_spi_armed && (now_ms - s_arm_tick_ms) > APP_SPI_ARM_TIMEOUT_MS)
    {
        (void)HAL_SPI_Abort(&hspi1);
        s_spi_armed = false;
        s_faults |= FAULT_SPI;
        app_debug_printf("[spi] transaction timeout, rearming\r\n");
    }

    if (s_rx_seen &&
        (now_ms - s_last_valid_rx_ms) > APP_SPI_LINK_TIMEOUT_MS)
    {
        if (s_link_state == APP_SPI_LINK_ACTIVE ||
            s_link_state == APP_SPI_LINK_WAIT_HELLO)
        {
            s_session_active = false;
            s_need_hello = true;
            s_link_state = APP_SPI_LINK_LOST;
            s_faults |= FAULT_LINK_LOST;
            app_perf_all_off();
            s_last_valid_rx_ms = now_ms;
            app_debug_printf("[spi] link lost, outputs off\r\n");
        }
    }
}

bool app_spi_link_is_active(void)
{
    return s_session_active && (s_link_state == APP_SPI_LINK_ACTIVE);
}

int32_t app_spi_link_temp_mc(void)
{
    return s_temp_seen ? s_temp_mc : 0;
}

uint16_t app_spi_link_temp_age_ms(uint32_t now_ms)
{
    if (!s_temp_seen)
    {
        return 0xFFFFU;
    }

    uint32_t age = now_ms - s_temp_sample_tick_ms;
    return (age > 0xFFFFU) ? 0xFFFFU : (uint16_t)age;
}

bool app_spi_link_temp_valid(uint32_t now_ms)
{
    if (!s_temp_seen || !s_temp_valid)
    {
        return false;
    }

    return (now_ms - s_temp_sample_tick_ms) <= APP_SPI_TEMP_MAX_AGE_MS;
}
