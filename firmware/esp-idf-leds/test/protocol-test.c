// Copyright (C) 2026 Toit contributors.
#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static led_parser_t parser;
static uint8_t packet[4105], output[LED_MAX_PIXELS * 4];

static size_t make_packet(uint32_t format, unsigned count, const uint8_t *data) {
    unsigned encoded = count - 1;
    packet[0] = format >> 16;
    packet[1] = format >> 8;
    packet[2] = format;
    packet[3] = encoded >> 8;
    packet[4] = encoded;
    packet[5] = packet[3] ^ packet[4] ^ 0x55;
    size_t length = count * (format == LED_ADALIGHT ? 3 : format == LED_AWA_RGBW ? 4 : 1);
    memcpy(packet + 6, data, length);
    if (format == LED_AWA_RGBW) {
        unsigned a = 0, b = 0, c = 0;
        for (unsigned i = 0; i < length; ++i) {
            a = (a + data[i]) % 255;
            b = (b + a) % 255;
            c = (c + (data[i] ^ (i & 255))) % 255;
        }
        packet[6 + length] = a;
        packet[7 + length] = b;
        packet[8 + length] = c == 0x41 ? 0xaa : c;
        length += 3;
    }
    return length + 6;
}

static unsigned feed(size_t length) {
    unsigned frames = 0;
    for (size_t i = 0; i < length; ++i) frames += led_parser_feed(&parser, packet[i]);
    return frames;
}

int main(void) {
    led_parser_reset(&parser);
    const uint8_t rgb[] = {255, 20, 9};
    size_t length = make_packet(LED_ADALIGHT, 1, rgb);
    const uint8_t noise[] = {0, 'A', 'A', 'd', 'a', 0, 0, 0};
    for (size_t i = 0; i < sizeof(noise); ++i) assert(!led_parser_feed(&parser, noise[i]));
    assert(feed(length) == 1);
    assert(led_render(&parser, output) == 4);
    assert(memcmp(output, (uint8_t[]){20, 255, 9, 0}, 4) == 0);

    const uint8_t rgbw[] = {1, 2, 3, 4};
    length = make_packet(LED_AWA_RGBW, 1, rgbw);
    packet[length - 1] ^= 1;
    assert(feed(length) == 0);
    length = make_packet(LED_AWA_RGBW, 1, rgbw);
    assert(feed(length) == 1);
    led_render(&parser, output);
    assert(memcmp(output, (uint8_t[]){2, 1, 3, 4}, 4) == 0);

    // Reject excessive counts before collecting payload bytes.
    memcpy(packet, (uint8_t[]){'A', 'd', 'a', 2, 0, 0x57}, 6);
    assert(feed(6) == 0);
    assert(parser.state == 0);

    uint8_t echo[4096];
    for (unsigned i = 0; i < sizeof(echo); ++i) echo[i] = i;
    length = make_packet(LED_ECHO, sizeof(echo), echo);
    assert(feed(length) == 1);
    assert(parser.count == sizeof(echo));
    assert(memcmp(parser.data, echo, sizeof(echo)) == 0);

    uint8_t full[LED_MAX_PIXELS * 4];
    memset(full, 255, sizeof(full));
    length = make_packet(LED_AWA_RGBW, LED_MAX_PIXELS, full);
    assert(feed(length) == 1);
    assert(led_render(&parser, output) == sizeof(output));
    unsigned sum = 0;
    for (unsigned i = 0; i < sizeof(output); ++i) sum += output[i];
    assert(sum * LED_CHANNEL_MA <= (LED_CURRENT_LIMIT_MA - LED_MAX_PIXELS * LED_IDLE_MA) * 255);

    // A bright picture concentrated on either feed must respect its port rating.
    for (unsigned section = 0; section < 2; ++section) {
        memset(full, 0, sizeof(full));
        unsigned first = section ? LED_FEED_SPLIT_PIXELS : 0;
        memset(full + first * 4, 255, LED_FEED_SPLIT_PIXELS * 4);
        length = make_packet(LED_AWA_RGBW, LED_FEED_SPLIT_PIXELS * 2, full);
        assert(feed(length) == 1);
        led_render(&parser, output);
        unsigned feed_sum = 0;
        for (unsigned i = first * 4; i < (first + LED_FEED_SPLIT_PIXELS) * 4; ++i)
            feed_sum += output[i];
        assert(feed_sum * LED_CHANNEL_MA
               <= (LED_FEED_LIMIT_MA - LED_FEED_SPLIT_PIXELS * LED_IDLE_MA) * 255);
    }

    // Grey levels keep their relative brightness instead of normalizing to white.
    const unsigned levels[] = {0, 16, 32, 64, 128, 255};
    unsigned previous = 0;
    for (unsigned step = 0; step < sizeof(levels) / sizeof(levels[0]); ++step) {
        memset(full, levels[step], sizeof(full));
        length = make_packet(LED_ADALIGHT, LED_FEED_SPLIT_PIXELS * 2, full);
        assert(feed(length) == 1);
        led_render(&parser, output);
        unsigned value = output[0];
        if (step == 0) assert(value == 0);
        else assert(value > previous);
        for (unsigned i = 0; i < LED_FEED_SPLIT_PIXELS * 2; ++i)
            assert(memcmp(output + i * 4, (uint8_t[]){value, value, value, 0}, 4) == 0);
        if (levels[step] == 128) assert(value >= 20 && value <= 22);
        if (levels[step] == 255) assert(value >= 42 && value <= 44);
        previous = value;
    }

    // Other LEDs getting brighter must not dim or brighten a reference pixel.
    memset(full, 0, sizeof(full));
    memcpy(full, (uint8_t[]){180, 90, 30}, 3);
    length = make_packet(LED_ADALIGHT, LED_FEED_SPLIT_PIXELS * 2, full);
    assert(feed(length) == 1);
    led_render(&parser, output);
    uint8_t reference[4];
    memcpy(reference, output, 4);
    assert(reference[0] > 0 && reference[1] > reference[0] && reference[0] > reference[2]);
    memset(full + 3, 255, sizeof(full) - 3);
    length = make_packet(LED_ADALIGHT, LED_FEED_SPLIT_PIXELS * 2, full);
    assert(feed(length) == 1);
    led_render(&parser, output);
    assert(memcmp(output, reference, 4) == 0);

    // A short layout can be constrained by one USB port before the total limit.
    memset(full, 255, sizeof(full));
    length = make_packet(LED_AWA_RGBW, LED_FEED_SPLIT_PIXELS, full);
    assert(feed(length) == 1);
    led_render(&parser, output);
    unsigned first_feed_sum = 0;
    for (unsigned i = 0; i < LED_FEED_SPLIT_PIXELS * 4; ++i) first_feed_sum += output[i];
    assert(first_feed_sum * LED_CHANNEL_MA
           <= (LED_FEED_LIMIT_MA - LED_FEED_SPLIT_PIXELS * LED_IDLE_MA) * 255);

    // Feed arbitrary binary noise under ASan/UBSan, including incomplete frames.
    uint32_t random = 17;
    for (unsigned i = 0; i < 100000; ++i) {
        random = random * 1664525u + 1013904223u;
        led_parser_feed(&parser, random >> 24);
    }
    led_parser_reset(&parser);
    assert(feed(length) == 1);
    puts("PASS: protocol, fixed brightness/contrast, pixel context independence, total/feed limits, and binary noise.");
}
