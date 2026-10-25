# ESP32-S3 USB LED receiver

Native ESP-IDF firmware for SK6812 RGBW LEDs on GPIO 9. The TV sends colour
packets through the ESP32-S3's native USB Serial/JTAG CDC interface. No Wi-Fi
or OTA service runs on the board. See the [main README](../../README.md) for
wiring, builds, flashing, and TV configuration.

## Output

RMT runs at 10 MHz with DMA, a 1024-symbol buffer, interrupt priority 3, and an
IRAM-safe ISR. The complete waveform is prepared in internal RAM; a copy encoder
feeds it to DMA. The buffer remains unchanged until transmission completes.

Zero uses 300 ns high / 900 ns low; one uses 600 ns high / 600 ns low. Frames
have 300 µs low at both ends. These values follow page 5 of the
[SK6812RGBW datasheet](https://addressable-led.com/UploadFile/upi/file/20170620/SK6812RGBW%20LED.pdf).
See also the [ESP-IDF RMT documentation](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32s3/api-reference/peripherals/rmt.html).

Output byte order is GRBW. RGB input leaves W off. Fixed brightness gain depends
only on the pixel count, input format, and power budgets. It maps worst-case
full white to an estimated 3 A total / 2.4 A per feed, preserving dark levels.
The feed split is index 133; change `protocol.h` for different wiring/budgets.
Current estimates use 1 mA idle per pixel and 20 mA per full channel.

The receiver accepts up to 512 pixels. Startup and a one-second frame timeout
clear 520 addresses. Every output frame appends eight black pixels; a shorter
frame also clears the preceding frame's extra pixels. An incomplete packet is
discarded after 250 ms without USB input. USB RX/TX buffers are 8192/4096 bytes;
console logs go to UART0 so they do not contaminate the binary USB protocol.

## Wire protocol

Each packet starts with a three-byte magic, a two-byte big-endian count minus
one, and a header checksum: `countHigh ^ countLow ^ 0x55`.

| Magic | Count means | Payload | Trailer |
| --- | --- | --- | --- |
| `Ada` | Pixels, 1–512 | RGB bytes per pixel | None |
| `AWa` | Pixels, 1–512 | RGBW bytes per pixel | Three checksum bytes |
| `Ech` | Bytes, 1–4096 | Arbitrary bytes | None; echoed unchanged |

The `AWa` checksum covers the payload, indexed from zero:

```text
sum1 = sum2 = extended = 0
for each byte value at index i:
    sum1 = (sum1 + value) % 255
    sum2 = (sum2 + sum1) % 255
    extended = (extended + (value XOR (i AND 255))) % 255
if extended == 0x41: extended = 0xaa
trailer = [sum1, sum2, extended]
```

The normal HyperHDR configuration uses `Ada`. `Ech` is a transport diagnostic;
stop live serial output before using `tools/test-native-usb-echo.py` with
`--serial VERIFIED_USB_SERIAL --framed`. Run that script on the USB host (the
TV for this setup); it supports Python 2.7 and 3 and uses only the standard library.
It neither flashes nor resets the board.

## Build variants

| Build script argument | Behaviour | Output directory |
| --- | --- | --- |
| `live` (default) | USB colour receiver | `build/esp-idf-leds/` |
| `standalone` | Clear strip, green PWM 16 on first 266 pixels once, then hold data low | `build/esp-idf-leds-test/` |
| `standalone-repeat` | Repeat the same green frame at about 30 Hz | `build/esp-idf-leds-test/` |

Each directory contains `tv_leds_native.bin`. Standalone modes install no USB
receiver; the strip must already be powered when the one-shot test starts.
The standalone pixel count is in `main.c`. Reflash the live variant to resume
ambient lighting. ESP-IDF and its generated files stay outside the source tree.
