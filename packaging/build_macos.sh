#!/usr/bin/env bash
# Build the macOS .app for Tirut PDF, with a self-contained Tesseract OCR engine
# bundled inside it, and package a .dmg. Signing/notarization is a separate step
# (packaging/sign_notarize_macos.sh) that you run with your Apple Developer ID.
set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/Tirut PDF.app"
RES_VENDOR="$APP/Contents/Resources/vendor"

python -m pip install --quiet pyinstaller
python tools/make_icon.py

# 1) Self-contained Tesseract -> vendor/tesseract (idempotent; refreshes each build).
bash tools/bundle_tesseract_macos.sh

# 2) Build the app (the spec deliberately does NOT pack vendor/ on macOS).
rm -rf build dist
pyinstaller packaging/Slate.spec --noconfirm

# 3) Copy the Tesseract toolchain into the app VERBATIM (PyInstaller must not touch it,
#    or it dedups/version-swaps the shared dylibs). Relative @executable_path/../lib
#    links stay valid because bin/ and lib/ are copied together.
mkdir -p "$RES_VENDOR"
cp -R vendor/tesseract "$RES_VENDOR/"
chmod +x "$RES_VENDOR/tesseract/bin/tesseract"

# 4) Sanity check: the in-app Tesseract must run self-contained (clean env, no PATH).
env -i TESSDATA_PREFIX="$RES_VENDOR/tesseract/share/tessdata" \
    "$RES_VENDOR/tesseract/bin/tesseract" --version >/dev/null \
    && echo "✓ bundled Tesseract runs self-contained" \
    || { echo "✗ bundled Tesseract failed to run"; exit 1; }

# 5) Package a .dmg (drag-to-Applications).
DMG="dist/Tirut PDF.dmg"
rm -f "$DMG"
hdiutil create -volname "Tirut PDF" -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
echo
echo "Built: $APP"
echo "Built: $DMG"
echo "Next: sign + notarize with  bash packaging/sign_notarize_macos.sh  (needs your Apple Developer ID)."
