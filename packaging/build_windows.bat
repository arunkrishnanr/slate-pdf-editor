@echo off
REM ===================================================================
REM  Build Tirut PDF for Windows (one-folder app + optional installer).
REM  Run this on a Windows PC (Python 3.10+ installed). Results:
REM      dist\Tirut PDF\            <- the app folder (copy-and-run portable)
REM      dist\Tirut PDF\Tirut PDF.exe
REM      dist\TirutPDF-Setup.exe    <- installer (if Inno Setup is installed)
REM  One-folder (not one-file) is deliberate: it does NOT self-extract at
REM  launch, which avoids the SmartScreen / antivirus false-positives that
REM  one-file PyInstaller exes trigger.
REM ===================================================================
setlocal
cd /d "%~dp0\.."

echo [1/5] Creating virtual environment...
if not exist .venv (
    py -3.10 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [2/5] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller >nul

echo [3/5] Generating icon...
python tools\make_icon.py

echo [4/5] Building one-folder app...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller packaging\Slate.spec --noconfirm

echo [5/5] Building installer (if Inno Setup 6 is installed)...
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" packaging\windows_installer.iss
) else (
    echo  Inno Setup 6 not found - skipping installer.
    echo  Get it from https://jrsoftware.org/isdl.php to build dist\TirutPDF-Setup.exe
)

echo.
echo ===================================================================
echo  Done.
echo   Portable : dist\Tirut PDF\  (copy the whole folder, run Tirut PDF.exe)
echo   Installer: dist\TirutPDF-Setup.exe  (if built above)
echo ===================================================================
echo.
echo  TRUST: to remove the SmartScreen "unknown publisher" warning you must
echo  sign BOTH files with your code-signing certificate, e.g.:
echo    signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
echo      /f your_cert.pfx /p PW "dist\Tirut PDF\Tirut PDF.exe"
echo    signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
echo      /f your_cert.pfx /p PW "dist\TirutPDF-Setup.exe"
echo  Sign the app exe BEFORE building the installer so both are covered.
echo.
echo  OCR note: offline OCR (Tesseract) is bundled automatically by CI. For a
echo  local build, put tesseract.exe + tessdata\ under vendor\tesseract\ first.
pause
