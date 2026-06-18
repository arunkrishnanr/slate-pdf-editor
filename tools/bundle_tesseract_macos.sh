#!/usr/bin/env bash
# Bundle a self-contained Tesseract OCR engine into vendor/tesseract/ so Tirut PDF
# ships OCR inside the app (never touching the user's system).
#
# Produces:
#   vendor/tesseract/bin/tesseract        (relocated: deps -> @executable_path/../lib)
#   vendor/tesseract/lib/*.dylib          (its homebrew dylib closure)
#   vendor/tesseract/share/tessdata/*.traineddata
#
# Run on macOS with Homebrew's tesseract installed. Re-run to refresh.
set -euo pipefail
cd "$(dirname "$0")/.."

TESS_BIN="$(command -v tesseract)"
[ -n "$TESS_BIN" ] || { echo "tesseract not found (brew install tesseract)"; exit 1; }
TPREFIX="$(brew --prefix tesseract)"

DEST="vendor/tesseract"
rm -rf "$DEST"
mkdir -p "$DEST/bin" "$DEST/lib" "$DEST/share/tessdata"

cp "$TESS_BIN" "$DEST/bin/tesseract"
chmod +w "$DEST/bin/tesseract"

# Recursively copy + relocate the (non-system) dylib dependencies.
dylibbundler -of -cd -b \
  -x "$DEST/bin/tesseract" \
  -d "$DEST/lib/" \
  -p "@executable_path/../lib/" >/dev/null

# Language data: English + orientation/script. Add more *.traineddata here if needed.
for td in eng.traineddata osd.traineddata; do
  for src in "$TPREFIX/share/tessdata/$td" "$(brew --prefix)/share/tessdata/$td"; do
    [ -f "$src" ] && cp "$src" "$DEST/share/tessdata/" && break
  done
done

echo "Bundled Tesseract -> $DEST"
echo "  binary deps now:"
otool -L "$DEST/bin/tesseract" | sed -n '2,$p' | sed 's/^/    /'
echo "  tessdata: $(ls "$DEST/share/tessdata/" | tr '\n' ' ')"
