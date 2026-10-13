#!/bin/bash
# Builds the Release configuration of the Neema iOS app as an .xcarchive, and
# with an Apple team signs it and exports the .ipa for TestFlight.
#
#   scripts/release.sh                      # unsigned archive in build/ (what CI does)
#   scripts/release.sh --build 42           # the build number (CFBundleVersion); the version stays project.yml's
#   scripts/release.sh --version 1.0.1 --build 42 --team ABCDE12345
#                                           # signed with that team, exported with scripts/ExportOptions.plist
#
# The team can also come from NEEMA_APPLE_TEAM. Without one the archive is
# unsigned (CODE_SIGNING_ALLOWED=NO): it proves the optimised build and the
# archive step, and cannot be installed on a phone. docs/ios/RELEASE.md has
# the whole path to TestFlight.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=""
BUILD=""
TEAM="${NEEMA_APPLE_TEAM:-}"
OUT="build"
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --build) BUILD="$2"; shift 2 ;;
    --team) TEAM="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -d Neema.xcodeproj ] || xcodegen generate
mkdir -p "$OUT"
ARCHIVE="$OUT/Neema.xcarchive"
rm -rf "$ARCHIVE"

OVERRIDES=()
[ -n "$VERSION" ] && OVERRIDES+=("MARKETING_VERSION=$VERSION")
[ -n "$BUILD" ] && OVERRIDES+=("CURRENT_PROJECT_VERSION=$BUILD")
if [ -n "$TEAM" ]; then
  SIGNING=("DEVELOPMENT_TEAM=$TEAM" "-allowProvisioningUpdates")
else
  SIGNING=("CODE_SIGNING_ALLOWED=NO" "CODE_SIGNING_REQUIRED=NO" "CODE_SIGN_IDENTITY=")
fi

# ${arr[@]+"${arr[@]}"}: an empty array is not an unbound variable on macOS's bash 3.2.
xcodebuild archive -project Neema.xcodeproj -scheme Neema -configuration Release \
  -destination "generic/platform=iOS" -archivePath "$ARCHIVE" -skipPackagePluginValidation \
  ${OVERRIDES[@]+"${OVERRIDES[@]}"} "${SIGNING[@]}" \
  2>&1 | tee "$OUT/archive.log" | grep -E "error:|\*\* " || true
grep -q "\*\* ARCHIVE SUCCEEDED \*\*" "$OUT/archive.log"

APP="$ARCHIVE/Products/Applications/Neema.app"
# The Release app carries no test fixtures (the recorded backend is Debug only).
if [ -e "$APP/fixtures.json" ]; then echo "error: the Release app bundles fixtures.json" >&2; exit 1; fi
PLIST="$APP/Info.plist"
echo "Archived Neema $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST") (build $(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$PLIST")) → $ARCHIVE"

if [ -z "$TEAM" ]; then
  echo "Unsigned (no team): not exportable. Pass --team or set NEEMA_APPLE_TEAM to sign and export."
  exit 0
fi

sed "s/TEAM_ID/$TEAM/" scripts/ExportOptions.plist > "$OUT/ExportOptions.plist"
xcodebuild -exportArchive -archivePath "$ARCHIVE" -exportOptionsPlist "$OUT/ExportOptions.plist" \
  -exportPath "$OUT/export" -allowProvisioningUpdates 2>&1 | tee "$OUT/export.log" | grep -E "error:|\*\* " || true
grep -q "\*\* EXPORT SUCCEEDED \*\*" "$OUT/export.log"
echo "Exported → $OUT/export (upload with Transporter, or: xcrun altool --upload-app -f $OUT/export/Neema.ipa -t ios --apiKey … --apiIssuer …)"
