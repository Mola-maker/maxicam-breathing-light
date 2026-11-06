#ifndef APP_SPI_LINK_H
#define APP_SPI_LINK_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>

#define APP_SPI_FRAME_SIZE         64U
#define APP_SPI_PROTOCOL_VERSION   1U

typedef enum
{
    APP_SPI_LINK_BOOT = 0,
    APP_SPI_LINK_WAIT_HELLO,
    APP_SPI_LINK_ACTIVE,
    APP_SPI_LINK_LOST,
    APP_SPI_LINK_FAULT
} app_spi_link_state_t;

void app_spi_link_init(uint32_t now_ms);
void app_spi_link_poll(uint32_t now_ms);
bool app_spi_link_is_active(void);
int32_t app_spi_link_temp_mc(void);
uint16_t app_spi_link_temp_age_ms(uint32_t now_ms);
bool app_spi_link_temp_valid(uint32_t now_ms);

#ifdef __cplusplus
}
#endif

#endif /* APP_SPI_LINK_H */
