#!/usr/bin/env bash
# Copyright (C) 2026 Toit contributors.
set -euo pipefail
cd "$(dirname "$0")/.."
sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"
tools_version="${ANDROID_BUILD_TOOLS:-36.0.0}"
platform="${ANDROID_PLATFORM:-android-35}"
build_tools="$sdk_root/build-tools/$tools_version"
android_jar="$sdk_root/platforms/$platform/android.jar"
for executable in aapt2 d8 zipalign apksigner; do
    test -x "$build_tools/$executable" || { echo "Missing $build_tools/$executable" >&2; exit 1; }
done
test -f "$android_jar" || { echo "Missing $android_jar" >&2; exit 1; }
mkdir -p build/classes build/dex
# Clear generated classes so deleted Java files cannot linger in the APK.
find build/classes build/dex -type f -delete
"$build_tools/aapt2" link -I "$android_jar" --manifest app/AndroidManifest.xml -o build/base.apk
find app/src -name '*.java' -print > build/sources.txt
javac --release 8 -classpath "$android_jar" -d build/classes @build/sources.txt
jar cf build/classes.jar -C build/classes .
"$build_tools/d8" --min-api 26 --lib "$android_jar" --output build/dex build/classes.jar
cp build/base.apk build/with-dex.apk
(cd build/dex && zip -q -u ../with-dex.apk classes.dex)
"$build_tools/zipalign" -f 4 build/with-dex.apk build/aligned.apk
if [[ ! -f build/debug.keystore ]]; then
    keytool -genkeypair -keystore build/debug.keystore -storepass android -keypass android \
        -alias androiddebugkey -dname 'CN=Android Debug' -keyalg RSA -keysize 2048 -validity 10000
fi
"$build_tools/apksigner" sign --ks build/debug.keystore --ks-pass pass:android \
    --out build/tv-leds-patterns.apk build/aligned.apk
"$build_tools/apksigner" verify build/tv-leds-patterns.apk
echo "Built $(pwd)/build/tv-leds-patterns.apk"
