# PyInstaller spec for Tirut PDF.
#
#   macOS    : pyinstaller packaging/Slate.spec  -> dist/Tirut PDF.app
#   Windows  : pyinstaller packaging/Slate.spec  -> dist/Tirut PDF/  (one-folder app)
#
# On Windows this produces a ONE-FOLDER app (Tirut PDF.exe + its DLLs in a folder).
# This is the trusted, installer-friendly layout: Inno Setup packages the folder into
# Program Files, and — unlike a one-file exe — it does NOT self-extract a Python runtime
# to a temp dir at launch, which is the main trigger for SmartScreen / antivirus
# false-positives. A portable build is just this folder, zipped (copy-and-run).
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = os.path.abspath(os.getcwd())
RES = os.path.join(ROOT, "slate", "resources")
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

datas = [(RES, "slate/resources")]

# Bundle the self-contained Tesseract toolchain (vendor/) for offline OCR.
#   • Windows: let PyInstaller pack it into the one-file exe (extracted at runtime).
#   • macOS: do NOT add it here — PyInstaller dedups/rewrites same-named dylibs
#     (libpng/libtiff/… shared with PyMuPDF/OpenCV/Pillow), which silently swaps
#     Tesseract's libs and breaks it. build_macos.sh copies vendor/tesseract into the
#     .app verbatim instead, preserving the dylibbundler relocation untouched.
vendor = os.path.join(ROOT, "vendor")
if os.path.isdir(vendor) and IS_WIN:
    datas.append((vendor, "vendor"))

icon = os.path.join(RES, "icon.ico" if IS_WIN else "icon.icns")
manifest = os.path.join(ROOT, "packaging", "tirut.manifest")
win_version = os.path.join(ROOT, "packaging", "win_version_info.txt")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("fitz") + ["pytesseract", "cv2", "numpy",
                  "cryptography", "cryptography.hazmat.primitives.asymmetric.ed25519"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_WIN:
    # --- One-folder Windows app (trusted, installer-friendly; no runtime self-extract) ---
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="Tirut PDF",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,                      # UPX-packed exes are a common AV false-positive trigger
        console=False,                  # GUI app: no console window
        disable_windowed_traceback=False,
        icon=icon,
        manifest=manifest if os.path.exists(manifest) else None,
        version=win_version if os.path.exists(win_version) else None,
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
                   strip=False, upx=False, name="Tirut PDF")
else:
    # --- macOS one-folder + .app bundle ---
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="Tirut PDF",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=False, disable_windowed_traceback=False, icon=icon,
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
                   strip=False, upx=False, name="Tirut PDF")
    if IS_MAC:
        app = BUNDLE(
            coll,
            name="Tirut PDF.app",
            icon=os.path.join(RES, "icon.icns"),
            bundle_identifier="com.tirut.pdf",
            info_plist={
                "CFBundleName": "Tirut PDF",
                "CFBundleDisplayName": "Tirut PDF",
                "CFBundleShortVersionString": "1.0.0",
                "CFBundleVersion": "1.0.0",
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "11.0",
                "CFBundleDocumentTypes": [{
                    "CFBundleTypeName": "PDF Document",
                    "CFBundleTypeExtensions": ["pdf"],
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                }],
            },
        )
