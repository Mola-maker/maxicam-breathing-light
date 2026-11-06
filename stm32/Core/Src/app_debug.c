#include "app_debug.h"

#include "main.h"
#include "usart.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

void app_debug_init(void)
{
    static const char banner[] = "\r\nPWM-Heater STM32 ready\r\n";
    (void)HAL_UART_Transmit(&huart3, (uint8_t *)banner,
                            (uint16_t)(sizeof(banner) - 1U), 50U);
}

void app_debug_printf(const char *format, ...)
{
    char buffer[128];
    va_list args;
    int length;

    if (format == NULL)
    {
        return;
    }

    va_start(args, format);
    length = vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);

    if (length <= 0)
    {
        return;
    }

    if ((uint32_t)length >= sizeof(buffer))
    {
        length = (int)sizeof(buffer) - 1;
    }

    (void)HAL_UART_Transmit(&huart3, (uint8_t *)buffer,
                            (uint16_t)length, 50U);
}
