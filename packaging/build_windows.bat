@echo off
REM ===================================================================
REM  Build a PORTABLE one-click Windows .exe for Slate PDF Editor.
REM  Run this on a Windows PC (Python 3.10+ installed). Result:
REM      dist\Slate PDF Editor.exe   <- single self-contained file
REM  No installer, no folder, no terminal window. Just double-click.
REM ===================================================================
setlocal
cd /d "%~dp0\.."

echo [1/4] Creating virtual environment...
if not exist .venv (
    py -3.10 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller >nul

echo [3/4] Generating icon...
python tools\make_icon.py

echo [4/4] Building portable exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller packaging\Slate.spec --noconfirm

echo.
echo ===================================================================
echo  Done.  Portable program:  dist\Slate PDF Editor.exe
echo  Copy that single file anywhere (USB stick, Desktop) and run it.
echo ===================================================================
echo.
echo  OCR note: to bundle offline OCR into the exe, before building put
echo  tesseract.exe and its tessdata\ folder under  vendor\  then rerun.
pause
