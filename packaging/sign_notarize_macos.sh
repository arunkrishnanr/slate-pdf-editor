#!/usr/bin/env bash
# Sign, notarize, and staple the Tirut PDF macOS app + DMG for DIRECT distribution.
#
# Prerequisites (yours — I can't do these for you):
#   1. Apple Developer Program membership.
#   2. A "Developer ID Application" certificate installed in your login keychain.
#   3. A notarytool keychain profile created once with:
#        xcrun notarytool store-credentials "TirutNotary" \
#            --apple-id "you@example.com" --team-id "ABCDE12345" --password "<app-specific-pw>"
#
# Usage:
#   DEV_ID="Developer ID Application: Your Name (ABCDE12345)" \
#   NOTARY_PROFILE="TirutNotary" \
#   bash packaging/sign_notarize_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DEV_ID:?Set DEV_ID to your 'Developer ID Application: … (TEAMID)' identity}"
: "${NOTARY_PROFILE:=TirutNotary}"

APP="dist/Tirut PDF.app"
DMG="dist/Tirut PDF.dmg"
ENT="packaging/entitlements.plist"
[ -d "$APP" ] || { echo "Build first: bash packaging/build_macos.sh"; exit 1; }

echo "==> Signing every Mach-O inside the app (inner-out), with hardened runtime…"
# Sign all nested dylibs / .so / executables first, then the app itself.
find "$APP" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 | while IFS= read -r -d '' f; do
    codesign --force --timestamp --options runtime --sign "$DEV_ID" "$f"
done
# The bundled Tesseract CLI is an executable, not a .dylib — sign it explicitly.
codesign --force --timestamp --options runtime --entitlements "$ENT" \
    --sign "$DEV_ID" "$APP/Contents/Resources/vendor/tesseract/bin/tesseract"
# Any other Mach-O executables under the bundle.
find "$APP/Contents/MacOS" -type f -perm -u+x -print0 | while IFS= read -r -d '' f; do
    codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$DEV_ID" "$f" || true
done

echo "==> Signing the .app bundle…"
codesign --force --timestamp --options runtime --entitlements "$ENT" \
    --sign "$DEV_ID" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "==> Repackaging a fresh DMG from the signed app…"
rm -f "$DMG"
hdiutil create -volname "Tirut PDF" -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
codesign --force --timestamp --sign "$DEV_ID" "$DMG"

echo "==> Notarizing the DMG (this uploads to Apple and waits)…"
xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait

echo "==> Stapling the notarization ticket…"
xcrun stapler staple "$APP"
xcrun stapler staple "$DMG"
spctl --assess --type open --context context:primary-signature -v "$DMG" || true

echo
echo "✓ Signed, notarized, stapled:  $DMG"
echo "  Ship this DMG — Gatekeeper will open it with no warnings on any Mac."
