#!/usr/bin/env bash
# The two APKs every Android change ships as:
#
#   Neema-Android-<version>-<sha>.apk      every Android phone / tablet (universal)
#   Neema-TabS9Ultra-<version>-<sha>.apk   Samsung Galaxy Tab S9 Ultra (arm64-v8a,
#                                          the Snapdragon 8 Gen 2's ABI — smaller)
#
# Same app and same signing key: the tablet layouts are built in and switch on
# from the window size, so either installs over the last build.
#
# Usage: scripts/two-apks.sh [out-dir]      (default: app/build/outputs/two-apks)
#        SKIP_BUILD=1 scripts/two-apks.sh   (package an assembleRelease already run)
set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:-app/build/outputs/two-apks}"
[ "${SKIP_BUILD:-}" = "1" ] || ./gradlew :app:assembleRelease --no-daemon -q

version=$(grep -oP 'versionName = "\K[^"]+' app/build.gradle.kts)
sha=$(git rev-parse --short HEAD 2>/dev/null || echo local)
apks=app/build/outputs/apk/release

mkdir -p "$out"
cp "$apks/app-universal-release.apk" "$out/Neema-Android-${version}-${sha}.apk"
cp "$apks/app-arm64-v8a-release.apk" "$out/Neema-TabS9Ultra-${version}-${sha}.apk"
ls -1 "$out"/Neema-*-"${version}-${sha}".apk
