#!/usr/bin/env python3
"""Launch Tirut PDF from a source checkout:  python run.py [file.pdf ...]

Hidden flag:  --selftest  imports the full module graph (including native bindings
like cryptography and OpenCV) and verifies the license verifier loads, then exits
0/non-zero WITHOUT opening a window. CI runs the packaged exe this way to prove the
build is actually loadable."""

import sys


def _selftest() -> int:
    """Import everything the app needs and sanity-check the license crypto. Returns an
    exit code. Kept exception-safe so a packaged (windowed) build exits cleanly instead
    of popping a traceback dialog that would hang CI."""
    try:
        import base64
        import fitz            # noqa: F401  PyMuPDF
        import cv2             # noqa: F401  OpenCV
        import numpy           # noqa: F401
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from slate import (licensing, ocr, font_manager, structure,   # noqa: F401
                           text_editor, pdf_document, main_window)
        # the embedded public key must load, and the entitlement check must run
        Ed25519PublicKey.from_public_bytes(base64.b64decode(licensing.PUBLIC_KEY_B64))
        licensing.status()
        sys.stderr.write("SELFTEST OK\n")
        return 0
    except Exception as e:  # noqa: BLE001
        try:
            sys.stderr.write(f"SELFTEST FAIL: {type(e).__name__}: {e}\n")
        except Exception:
            pass
        return 2


if "--selftest" in sys.argv:
    sys.exit(_selftest())

# Verify required runtime tools BEFORE importing the heavy app modules. If something
# essential is missing, the user gets a clear error (with download links) and we exit.
from slate.preflight import run_or_exit
run_or_exit()

from slate.app import main

if __name__ == "__main__":
    main()
