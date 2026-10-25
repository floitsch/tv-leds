// Copyright (C) 2026 Toit contributors.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LED_MAX_PIXELS 512
#define LED_CURRENT_LIMIT_MA 3000
#define LED_FEED_LIMIT_MA 2400
#define LED_FEED_SPLIT_PIXELS 133
#define LED_CHANNEL_MA 20
#define LED_IDLE_MA 1
#define LED_ADALIGHT 0x416461u
#define LED_AWA_RGBW 0x415761u
#define LED_ECHO 0x456368u

typedef struct {
    uint32_t magic, format;
    unsigned state, used, count, length;
    uint8_t header[3], checksum[3], data[4096];
} led_parser_t;

void led_parser_reset(led_parser_t *parser);
// A completed frame remains in parser->data until the next input byte.
bool led_parser_feed(led_parser_t *parser, uint8_t byte);
// Output is GRBW with a content-independent brightness gain and current ceiling.
// Destination must hold LED_MAX_PIXELS * 4 bytes.
size_t led_render(const led_parser_t *parser, uint8_t *destination);
