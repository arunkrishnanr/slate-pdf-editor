# Tirut PDF — Distribution Guide

**Model chosen: direct distribution** (notarized `.dmg` on macOS, signed installer/`.exe`
on Windows). Tesseract OCR is **bundled inside the app** and never touches the user's
system.

## Why not the Mac App Store / Microsoft Store (yet)

Both stores require **sandboxed**, self-contained apps that may **not install or modify
other software** on the user's machine. Two consequences for this app:

- A "detect & update the system's Tesseract" behavior is **disqualifying** in both stores.
  (That's why we bundle Tesseract *inside* the app instead.)
- The Mac App Store is very hard to pass for a PyInstaller Python app that bundles and runs
  a Tesseract CLI. Direct, notarized distribution is the reliable path for this app.

Moving to the stores later means: add sandbox entitlements, keep tools bundle-only (already
true), and significant MAS-specific rework. The current build is store-friendly in spirit
(bundle-only) but distributed directly.

---

## macOS  (build + verify here; you sign)

```bash
bash packaging/build_macos.sh
```
Produces `dist/Tirut PDF.app` (Tesseract 5.5.2 bundled, verified self-contained) and
`dist/Tirut PDF.dmg`.

Then sign + notarize (needs **your** Apple Developer ID — I can't do this part):
```bash
# one-time:
xcrun notarytool store-credentials "TirutNotary" \
    --apple-id "you@example.com" --team-id "ABCDE12345" --password "<app-specific-pw>"
# each release:
DEV_ID="Developer ID Application: Your Name (ABCDE12345)" \
NOTARY_PROFILE="TirutNotary" \
bash packaging/sign_notarize_macos.sh
```
Ship the resulting **notarized, stapled `dist/Tirut PDF.dmg`** — opens with no Gatekeeper
warning on any Mac.

Prerequisites: Apple Developer Program ($99/yr), a *Developer ID Application* certificate
in your keychain.

## Windows  (builds on GitHub CI / a Windows machine; you sign)

The GitHub Actions workflow **Build Windows package** (`.github/workflows/build-windows.yml`)
on a `windows-latest` runner:
1. installs Python + deps,
2. installs Tesseract via Chocolatey and copies it into `vendor/tesseract/` (bundled, not
   system-touching),
3. builds the **one-folder** app `dist/Tirut PDF/` (`Tirut PDF.exe` + its DLLs + bundled
   Tesseract under `vendor/`),
4. builds the installer `dist/TirutPDF-Setup.exe` via Inno Setup.

Two artifacts are uploaded: **TirutPDF-windows-installer** (the Setup .exe) and
**TirutPDF-windows-portable** (the app folder, zipped — copy-and-run, no install).

Trigger it from the Actions tab → *Run workflow*, then download the artifacts.

### Why one-folder (this is the "trusted installer" part)

The Windows build is **one-folder**, not a one-file exe, on purpose. A one-file PyInstaller
exe unpacks an entire Python runtime to a temp directory on every launch — behaviour that
Windows Defender / antivirus heuristics flag as dropper-like, the main cause of false
positives. The one-folder app + an app manifest (`packaging/tirut.manifest`: `asInvoker`,
per-monitor DPI, Win 7–11 compatibility) behaves like a normal program and minimises those
flags. UPX compression is also disabled for the same reason.

### The actual trust anchor: code signing (yours)

Manifest + metadata reduce *antivirus* suspicion but do **not** silence SmartScreen's
"Windows protected your PC / unknown publisher" prompt. Only a **code-signing certificate**
does that:

- **OV certificate** (~$200–400/yr): the warning clears once the signed app accrues download
  *reputation* (can take days–weeks and some number of installs).
- **EV certificate** (~$300–600/yr): instant SmartScreen trust, no reputation wait.

Sign **both** the app exe and the installer, and sign the app exe **before** building the
installer so it's covered inside:
```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p PW "dist\Tirut PDF\Tirut PDF.exe"
:: now build the installer (ISCC packaging\windows_installer.iss), then:
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p PW "dist\TirutPDF-Setup.exe"
```
(Or set Inno's `[Setup] SignTool=` directive to sign automatically during the build.)

> Note: the Windows build is produced and validated on Windows/CI — it cannot be compiled
> on macOS. The macOS package is fully built and verified here.

## What I cannot do for you (account/credential-gated)

- Create Apple Developer / Microsoft Partner Center accounts.
- Code-sign or notarize (your certificates / Apple ID).
- Submit to the stores.

Everything up to those steps is automated by the scripts above.
