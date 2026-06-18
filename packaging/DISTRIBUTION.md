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
3. builds `dist/Tirut PDF.exe` (one file, Tesseract inside),
4. builds `dist/TirutPDF-Setup.exe` via Inno Setup.

Trigger it from the Actions tab → *Run workflow*, then download the artifacts.

Then sign (needs **your** Windows code-signing certificate):
```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p PW "dist\Tirut PDF.exe"
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p PW "dist\TirutPDF-Setup.exe"
```
Prerequisites: an OV/EV code-signing certificate (an EV cert avoids SmartScreen warnings).

> Note: the Windows build is produced and validated on Windows/CI — it cannot be compiled
> on macOS. The macOS package above is fully built and verified here.

## What I cannot do for you (account/credential-gated)

- Create Apple Developer / Microsoft Partner Center accounts.
- Code-sign or notarize (your certificates / Apple ID).
- Submit to the stores.

Everything up to those steps is automated by the scripts above.
