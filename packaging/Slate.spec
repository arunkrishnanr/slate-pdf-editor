# PyInstaller spec for Slate PDF Editor.
#
#   macOS    : pyinstaller packaging/Slate.spec  -> dist/Slate PDF Editor.app
#   Windows  : pyinstaller packaging/Slate.spec  -> dist/Slate PDF Editor.exe   (single portable file)
#
# On Windows this produces a ONE-FILE, portable, no-install executable: double-click to run,
# nothing to extract, no terminal window.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = os.path.abspath(os.getcwd())
RES = os.path.join(ROOT, "slate", "resources")
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

datas = [(RES, "slate/resources")]

# Bundle a tesseract binary + tessdata if present in vendor/ (optional, for offline OCR).
vendor = os.path.join(ROOT, "vendor")
if os.path.isdir(vendor):
    datas.append((vendor, "vendor"))

icon = os.path.join(RES, "icon.ico" if IS_WIN else "icon.icns")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("fitz") + ["pytesseract"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if IS_WIN:
    # --- Single-file portable .exe (everything embedded, self-extracts at runtime) ---
    exe = EXE(
        pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
        name="Slate PDF Editor",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,                  # GUI app: no console window
        disable_windowed_traceback=False,
        icon=icon,
        version=os.path.join(ROOT, "packaging", "win_version_info.txt")
        if os.path.exists(os.path.join(ROOT, "packaging", "win_version_info.txt")) else None,
    )
else:
    # --- macOS one-folder + .app bundle ---
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="Slate PDF Editor",
        debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
        console=False, disable_windowed_traceback=False, icon=icon,
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
                   strip=False, upx=False, name="Slate PDF Editor")
    if IS_MAC:
        app = BUNDLE(
            coll,
            name="Slate PDF Editor.app",
            icon=os.path.join(RES, "icon.icns"),
            bundle_identifier="com.slate.pdfeditor",
            info_plist={
                "CFBundleName": "Slate PDF Editor",
                "CFBundleDisplayName": "Slate PDF Editor",
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
