#!/usr/bin/env bash
# The two APKs every Android change ships as:
#
#   Neema-Android-<version>-<sha>.apk      every Android phone: ARM 64-bit and
#                                          older 32-bit (the universal build
#                                          without x86 — emulators/Chromebooks
#                                          only — so it stays small enough to send)
#   Neema-TabS9Ultra-<version>-<sha>.apk   Samsung Galaxy Tab S9 Ultra (arm64-v8a,
#                                          the Snapdragon 8 Gen 2's ABI)
#
# Same app and same signing key: the tablet layouts are built in and switch on
# from the window size, so either installs over the last build.
#
# Usage: scripts/two-apks.sh [out-dir]      (default: app/build/outputs/two-apks)
#        SKIP_BUILD=1 scripts/two-apks.sh   (package an assembleRelease already run)
# Signing follows app/build.gradle.kts: NEEMA_KEYSTORE et al. when set (CI's
# production key), otherwise the committed development key.
set -euo pipefail
cd "$(dirname "$0")/.."

out="${1:-app/build/outputs/two-apks}"
[ "${SKIP_BUILD:-}" = "1" ] || ./gradlew :app:assembleRelease --no-daemon -q

version=$(grep -oP 'versionName = "\K[^"]+' app/build.gradle.kts)
sha=$(git rev-parse --short HEAD 2>/dev/null || echo local)
apks=app/build/outputs/apk/release

sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$(grep -oP '^sdk.dir=\K.*' local.properties 2>/dev/null || true)}}"
tools=$(ls -d "$sdk"/build-tools/*/ | sort -V | tail -1)

mkdir -p "$out"
phone="$out/Neema-Android-${version}-${sha}.apk"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp "$apks/app-universal-release.apk" "$tmp/phone.apk"
zip -q -d "$tmp/phone.apk" 'lib/x86/*' 'lib/x86_64/*' 'META-INF/*.SF' 'META-INF/*.RSA' 'META-INF/*.EC' 'META-INF/*.MF' >/dev/null || true
"$tools/zipalign" -f -p 4 "$tmp/phone.apk" "$tmp/aligned.apk"
if [ -n "${NEEMA_KEYSTORE:-}" ] && [ -f "${NEEMA_KEYSTORE}" ]; then
  ks="$NEEMA_KEYSTORE"; ksp="$NEEMA_KEYSTORE_PASSWORD"; alias="$NEEMA_KEY_ALIAS"; kp="$NEEMA_KEY_PASSWORD"
else
  ks=keystore/dev.jks; ksp=neema-dev; alias=neema-dev; kp=neema-dev
fi
KSP="$ksp" KP="$kp" "$tools/apksigner" sign --ks "$ks" --ks-pass env:KSP --ks-key-alias "$alias" \
  --key-pass env:KP --out "$phone" "$tmp/aligned.apk"
"$tools/apksigner" verify "$phone"
rm -f "$phone.idsig"

cp "$apks/app-arm64-v8a-release.apk" "$out/Neema-TabS9Ultra-${version}-${sha}.apk"
ls -lh "$out"/Neema-*-"${version}-${sha}".apk | awk '{print $5, $9}'
