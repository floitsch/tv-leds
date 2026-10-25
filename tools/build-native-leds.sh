#!/usr/bin/env bash
# Copyright (C) 2026 Toit contributors.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
native_source="$project_root/firmware/esp-idf-leds"
build_dir="$project_root/build/esp-idf-leds"
idf_path="${IDF_PATH:?Set IDF_PATH to your ESP-IDF checkout (tested with 5.4)}"
defaults="$native_source/sdkconfig.defaults"
repeat_test=OFF
case "${1:-live}" in
    live) ;;
    standalone|standalone-repeat)
        build_dir="$project_root/build/esp-idf-leds-test"
        defaults="$defaults;$native_source/sdkconfig.test.defaults"
        if [[ "$1" == standalone-repeat ]]; then repeat_test=ON; fi
        ;;
    *) echo "Usage: $0 [live|standalone|standalone-repeat]" >&2; exit 2 ;;
esac
mkdir -p "$build_dir"
cc -std=c11 -Wall -Wextra -Werror -g -fsanitize=address,undefined \
    -I "$native_source/main" "$native_source/main/protocol.c" \
    "$native_source/test/protocol-test.c" -o "$build_dir/protocol-test"
"$build_dir/protocol-test"
# Keep SDK configuration and generated firmware inside the ignored build tree.
source "$idf_path/export.sh" > "$build_dir/idf-environment.log" 2>&1
idf.py -C "$native_source" -B "$build_dir" \
    -D SDKCONFIG="$build_dir/sdkconfig" \
    -D SDKCONFIG_DEFAULTS="$defaults" \
    -D TV_LEDS_REPEAT_TEST="$repeat_test" \
    -D IDF_TARGET=esp32s3 build
