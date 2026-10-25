// Copyright (C) 2026 Toit contributors.
#include <string.h>
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "driver/usb_serial_jtag.h"
#include "esp_check.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "protocol.h"

#define LED_GPIO 9
#define TAIL_CLEAR_PIXELS 8
#define OUTPUT_PIXELS (LED_MAX_PIXELS + TAIL_CLEAR_PIXELS)

static rmt_channel_handle_t channel;
static rmt_encoder_handle_t encoder;
static led_parser_t parser;
static uint8_t pixels[OUTPUT_PIXELS * 4];
// Pre-encode the complete waveform in internal RAM. The DMA encoder only copies it.
static rmt_symbol_word_t waveform[OUTPUT_PIXELS * 32 + 2];

static void show_pixels(size_t count) {
    const rmt_symbol_word_t reset = {.level0 = 0, .duration0 = 1500,
                                     .level1 = 0, .duration1 = 1500};
    size_t used = 0;
    waveform[used++] = reset;
    for (size_t i = 0; i < count * 4; ++i) {
        for (unsigned bit = 0; bit < 8; ++bit) {
            bool one = (pixels[i] & (0x80u >> bit)) != 0;
            // SK6812: 300/900 ns for zero, 600/600 ns for one.
            waveform[used++] = (rmt_symbol_word_t){
                .level0 = 1, .duration0 = one ? 6 : 3,
                .level1 = 0, .duration1 = one ? 6 : 9,
            };
        }
    }
    waveform[used++] = reset;
    const rmt_transmit_config_t config = {.loop_count = 0, .flags.eot_level = 0};
    ESP_ERROR_CHECK(rmt_transmit(channel, encoder, waveform,
                                used * sizeof(waveform[0]), &config));
    // Do not modify the waveform while the peripheral is reading it.
    ESP_ERROR_CHECK(rmt_tx_wait_all_done(channel, 100));
}

static void clear_pixels(void) {
    memset(pixels, 0, sizeof(pixels));
    show_pixels(OUTPUT_PIXELS);
}

static void echo_bytes(const uint8_t *data, size_t size) {
    int64_t deadline = esp_timer_get_time() + 1000000;
    while (size && esp_timer_get_time() < deadline) {
        int written = usb_serial_jtag_write_bytes(data, size, pdMS_TO_TICKS(20));
        if (written > 0) {
            data += written;
            size -= written;
        }
    }
}

void app_main(void) {
    const rmt_tx_channel_config_t tx = {
        .gpio_num = LED_GPIO,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10000000,
        .mem_block_symbols = 1024,
        .trans_queue_depth = 1,
        .intr_priority = 3,
        .flags.with_dma = true,
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&tx, &channel));
    const rmt_copy_encoder_config_t copy = {};
    ESP_ERROR_CHECK(rmt_new_copy_encoder(&copy, &encoder));
    ESP_ERROR_CHECK(rmt_enable(channel));
    clear_pixels();
#ifdef CONFIG_TV_LEDS_STANDALONE_TEST
    // About 0.6 A including the idle-current estimate.
    for (size_t i = 0; i < 266; ++i) pixels[i * 4] = 16;
    show_pixels(266 + TAIL_CLEAR_PIXELS);
#ifdef TV_LEDS_REPEAT_TEST
    TickType_t next_frame = xTaskGetTickCount();
    while (true) {
        vTaskDelayUntil(&next_frame, pdMS_TO_TICKS(33));
        show_pixels(266 + TAIL_CLEAR_PIXELS);
    }
#else
    while (true) vTaskDelay(pdMS_TO_TICKS(1000));
#endif
#endif
    usb_serial_jtag_driver_config_t usb = {
        .rx_buffer_size = 8192,
        .tx_buffer_size = 4096,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    esp_ota_img_states_t state;
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (esp_ota_get_state_partition(running, &state) == ESP_OK
        && state == ESP_OTA_IMG_PENDING_VERIFY)
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());

    led_parser_reset(&parser);
    uint8_t input[1024];
    int64_t last_frame = 0, last_input = 0;
    size_t previous_count = 0;
    bool lit = false;
    while (true) {
        int received = usb_serial_jtag_read_bytes(input, sizeof(input), pdMS_TO_TICKS(20));
        for (int i = 0; i < received; ++i) {
            if (!led_parser_feed(&parser, input[i])) continue;
            if (parser.format == LED_ECHO) {
                echo_bytes(parser.data, parser.count);
            } else {
                size_t bytes = led_render(&parser, pixels);
                size_t output_count = parser.count > previous_count ? parser.count : previous_count;
                // Clear a few extra pixels even if the calibrated count is slightly short.
                memset(pixels + bytes, 0, (output_count + TAIL_CLEAR_PIXELS) * 4 - bytes);
                show_pixels(output_count + TAIL_CLEAR_PIXELS);
                previous_count = parser.count;
                last_frame = esp_timer_get_time();
                lit = true;
            }
        }
        int64_t now = esp_timer_get_time();
        if (received > 0) last_input = now;
        else if (now - last_input > 250000) led_parser_reset(&parser);
        if (lit && now - last_frame > 1000000) {
            clear_pixels();
            previous_count = 0;
            lit = false;
        }
    }
}
