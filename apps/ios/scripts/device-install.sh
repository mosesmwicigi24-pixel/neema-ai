#!/bin/bash
# Builds Neema for a real iPhone or iPad plugged into this Mac, signs it with
# your Apple ID's team, installs it and opens it. A free Apple ID works (Xcode's
# "Personal Team"): the app then runs for 7 days before it needs reinstalling.
# A paid Apple Developer team has no such limit; TestFlight is RELEASE.md §4.
#
#   scripts/device-install.sh --team ABCDE12345
#   scripts/device-install.sh --team ABCDE12345 --device <udid>     # with several devices
#   scripts/device-install.sh --team ABCDE12345 --bundle-id ke.co.bethanyhouse.neema.moses
#
# The team id: Xcode → Settings → Accounts → your Apple ID → the team's "Team ID"
# (or developer.apple.com → Membership). The device needs Developer Mode on
# (Settings → Privacy & Security → Developer Mode) and to trust this Mac.
# --bundle-id: a free team cannot sign a bundle id another team registered;
# pass any unique one if Xcode says the id is not available.
set -euo pipefail
cd "$(dirname "$0")/.."

TEAM="${NEEMA_APPLE_TEAM:-}"
DEVICE=""
BUNDLE=""
CONFIG="Release"
while [ $# -gt 0 ]; do
  case "$1" in
    --team) TEAM="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    --bundle-id) BUNDLE="$2"; shift 2 ;;
    --debug) CONFIG="Debug"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$TEAM" ] || { echo "Pass --team <Team ID> (Xcode → Settings → Accounts)." >&2; exit 2; }
command -v xcodegen >/dev/null || { echo "Install XcodeGen first: brew install xcodegen" >&2; exit 2; }

if [ -z "$DEVICE" ]; then
  # The first connected iPhone or iPad (xctrace lists "Name (OS) (UDID)" lines under "== Devices ==").
  DEVICE=$(xcrun xctrace list devices 2>/dev/null \
    | awk '/^== Devices ==/{d=1;next} /^== /{d=0} d' \
    | grep -E "iPhone|iPad" | grep -v Simulator | head -1 \
    | sed -E 's/.*\(([0-9A-Fa-f-]{20,})\)[[:space:]]*$/\1/')
fi
[ -n "$DEVICE" ] || { echo "No iPhone or iPad found: plug one in, unlock it and trust this Mac." >&2; exit 1; }
echo "Device: $DEVICE"

xcodegen generate >/dev/null
OUT=build/device
OVERRIDES=("DEVELOPMENT_TEAM=$TEAM" "CODE_SIGN_STYLE=Automatic")
[ -n "$BUNDLE" ] && OVERRIDES+=("PRODUCT_BUNDLE_IDENTIFIER=$BUNDLE")

xcodebuild -project Neema.xcodeproj -scheme Neema -configuration "$CONFIG" \
  -destination "id=$DEVICE" -derivedDataPath "$OUT" -allowProvisioningUpdates \
  -skipPackagePluginValidation "${OVERRIDES[@]}" build \
  2>&1 | tee "$OUT.log" | grep -E "error:|\*\* " || true
grep -q "\*\* BUILD SUCCEEDED \*\*" "$OUT.log" || { echo "Build failed — see $OUT.log" >&2; exit 1; }

APP="$OUT/Build/Products/$CONFIG-iphoneos/Neema.app"
[ -d "$APP" ] || { echo "Built, but $APP is missing" >&2; exit 1; }
xcrun devicectl device install app --device "$DEVICE" "$APP"
BID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist")
xcrun devicectl device process launch --device "$DEVICE" "$BID" \
  || echo "Installed. If it will not open: Settings → General → VPN & Device Management → trust your Apple ID."
echo "Neema ($BID) is on the device."
