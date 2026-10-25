// Copyright (C) 2026 Toit contributors.
#include "protocol.h"
#include <string.h>

enum { SEEK, HEADER, PAYLOAD, CHECKSUM };

void led_parser_reset(led_parser_t *p) {
    p->state = SEEK;
    p->used = 0;
    p->magic = 0;
}

static bool checksum_valid(const led_parser_t *p) {
    unsigned sum1 = 0, sum2 = 0, extended = 0;
    for (unsigned i = 0; i < p->length; ++i) {
        sum1 = (sum1 + p->data[i]) % 255;
        sum2 = (sum2 + sum1) % 255;
        extended = (extended + (p->data[i] ^ (i & 255))) % 255;
    }
    if (extended == 0x41) extended = 0xaa;
    return p->checksum[0] == sum1 && p->checksum[1] == sum2
        && p->checksum[2] == extended;
}

bool led_parser_feed(led_parser_t *p, uint8_t byte) {
    switch (p->state) {
    case SEEK:
        p->magic = ((p->magic << 8) | byte) & 0xffffff;
        if (p->magic == LED_ADALIGHT || p->magic == LED_AWA_RGBW || p->magic == LED_ECHO) {
            p->format = p->magic;
            p->state = HEADER;
            p->used = 0;
        }
        break;
    case HEADER:
        p->header[p->used++] = byte;
        if (p->used != 3) break;
        p->count = ((unsigned)p->header[0] << 8 | p->header[1]) + 1;
        if (byte != (p->header[0] ^ p->header[1] ^ 0x55)
            || p->count > (p->format == LED_ECHO ? sizeof(p->data) : LED_MAX_PIXELS)) {
            led_parser_reset(p);
            break;
        }
        p->length = p->count * (p->format == LED_ADALIGHT ? 3 : p->format == LED_AWA_RGBW ? 4 : 1);
        p->state = PAYLOAD;
        p->used = 0;
        break;
    case PAYLOAD:
        p->data[p->used++] = byte;
        if (p->used != p->length) break;
        if (p->format == LED_AWA_RGBW) {
            p->state = CHECKSUM;
            p->used = 0;
        } else {
            led_parser_reset(p);
            return true;
        }
        break;
    case CHECKSUM:
        p->checksum[p->used++] = byte;
        if (p->used == 3) {
            bool valid = checksum_valid(p);
            led_parser_reset(p);
            return valid;
        }
        break;
    }
    return false;
}

static void constrain_scale(uint32_t sum, unsigned pixels, unsigned limit,
                            uint32_t *numerator, uint32_t *denominator) {
    uint32_t idle = pixels * LED_IDLE_MA;
    uint32_t available = limit > idle ? limit - idle : 0;
    uint32_t candidate_numerator = available * 255;
    uint32_t candidate_denominator = sum * LED_CHANNEL_MA;
    if (candidate_denominator
        && (uint64_t)candidate_numerator * *denominator
            < (uint64_t)*numerator * candidate_denominator) {
        *numerator = candidate_numerator;
        *denominator = candidate_denominator;
    }
}

size_t led_render(const led_parser_t *p, uint8_t *out) {
    if ((p->format != LED_ADALIGHT && p->format != LED_AWA_RGBW)
        || p->count == 0 || p->count > LED_MAX_PIXELS) return 0;
    unsigned stride = p->format == LED_ADALIGHT ? 3 : 4;
    unsigned first_feed_count = p->count < LED_FEED_SPLIT_PIXELS ? p->count : LED_FEED_SPLIT_PIXELS;
    unsigned second_feed_count = p->count - first_feed_count;

    // A fixed gain for this layout/format maps full white to the available
    // current budget. It must not depend on the contents of the image.
    uint32_t gain_numerator = 1, gain_denominator = 1;
    constrain_scale(p->count * stride * 255, p->count, LED_CURRENT_LIMIT_MA,
                    &gain_numerator, &gain_denominator);
    constrain_scale(first_feed_count * stride * 255, first_feed_count, LED_FEED_LIMIT_MA,
                    &gain_numerator, &gain_denominator);
    constrain_scale(second_feed_count * stride * 255, second_feed_count, LED_FEED_LIMIT_MA,
                    &gain_numerator, &gain_denominator);

    uint32_t sum = 0, first_feed_sum = 0;
    for (unsigned i = 0; i < p->count; ++i) {
        const uint8_t *source = p->data + i * stride;
        uint8_t *target = out + i * 4;
        target[0] = source[1];
        target[1] = source[0];
        target[2] = source[2];
        target[3] = stride == 4 ? source[3] : 0;
        for (unsigned c = 0; c < 4; ++c) {
            target[c] = (uint32_t)((uint64_t)target[c] * gain_numerator / gain_denominator);
            sum += target[c];
            if (i < LED_FEED_SPLIT_PIXELS) first_feed_sum += target[c];
        }
    }
    // Keep the measured-frame estimate as a final ceiling, not as brightness
    // normalization. The fixed gain should already fit these same budgets.
    uint32_t numerator = 1, denominator = 1;
    constrain_scale(sum, p->count, LED_CURRENT_LIMIT_MA, &numerator, &denominator);
    constrain_scale(first_feed_sum, first_feed_count, LED_FEED_LIMIT_MA, &numerator, &denominator);
    constrain_scale(sum - first_feed_sum, second_feed_count,
                    LED_FEED_LIMIT_MA, &numerator, &denominator);
    // Apply one scale to the whole frame to preserve spatial and colour ratios.
    if (numerator < denominator) {
        for (unsigned i = 0; i < p->count * 4; ++i)
            out[i] = (uint32_t)((uint64_t)out[i] * numerator / denominator);
    }
    return p->count * 4;
}
