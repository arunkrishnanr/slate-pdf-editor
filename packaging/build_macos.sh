#!/usr/bin/env bash
# Build the macOS .app bundle for Tirut PDF.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --quiet pyinstaller
python tools/make_icon.py
rm -rf build dist
pyinstaller packaging/Slate.spec --noconfirm

echo
echo "Built: dist/Tirut PDF.app"
echo "To create a .dmg installer:"
echo "  hdiutil create -volname 'Tirut PDF' -srcfolder 'dist/Tirut PDF.app' -ov -format UDZO 'dist/Tirut PDF.dmg'"
