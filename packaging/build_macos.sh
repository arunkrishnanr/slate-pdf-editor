#!/usr/bin/env bash
# Build the macOS .app bundle for Slate PDF Editor.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --quiet pyinstaller
python tools/make_icon.py
rm -rf build dist
pyinstaller packaging/Slate.spec --noconfirm

echo
echo "Built: dist/Slate PDF Editor.app"
echo "To create a .dmg installer:"
echo "  hdiutil create -volname 'Slate PDF Editor' -srcfolder 'dist/Slate PDF Editor.app' -ov -format UDZO 'dist/Slate PDF Editor.dmg'"
