# Tirut PDF — Windows test checklist

Run this on a **real Windows 10/11 PC** before signing or selling. Goal: confirm the app
installs, the core "wedge" works, and the trial/license/watermark logic behaves.

Report back per item: ✅ works / ❌ + what happened (screenshot or the exact error text).

## 0. Get the build
Download from the latest green **Build Windows package** run → Artifacts:
- `TirutPDF-windows-installer` → `TirutPDF-Setup.exe`
- `TirutPDF-windows-portable` → unzip, keep the folder together, run `Tirut PDF.exe`

Test the **installer** first (that's what customers use).

## 1. Install & first launch
- [ ] Double-click `TirutPDF-Setup.exe`. **Expected:** SmartScreen "unknown publisher" →
      *More info → Run anyway* (this is normal until code-signed). Note exactly what it says.
- [ ] Installer completes; Start-menu + desktop shortcut created; app launches.
- [ ] Title bar shows `Tirut PDF  [Trial — 14 days left]`.
- [ ] No console/terminal window appears behind it.

## 2. Core editing (the selling point)
- [ ] Open a normal text PDF. Turn on **Edit Mode**. Click a line of text, change it, confirm
      the edit lands *in place* (not a box over the old text). Save As a copy → reopen → edit persisted.
- [ ] Open a **scanned/image PDF**. Use **Tools → Recognize Text (OCR)** — text becomes selectable.
- [ ] Use the OCR region tool on scanned text, correct it, confirm the original is replaced in place.
- [ ] Sanity: zoom, page thumbnails, rotate/delete/reorder a page, print preview, undo/redo.

## 3. Licensing — trial (default state)
- [ ] OCR works during trial (no upsell prompt).
- [ ] Save a PDF → open it → **no watermark** (trial saves are clean).

## 4. Licensing — activate Pro
- [ ] Help → **Activate License…**, paste the **Pro test key** (from chat). Expect "Activated".
- [ ] Title bar badge disappears (or shows Pro); About shows "Licensed to…".
- [ ] Save still clean; OCR still works. Close & reopen the app → still Pro (persists).

## 5. Licensing — free/expired behavior
Simulate an expired trial (so you don't wait 14 days):
1. Close the app.
2. In File Explorer go to `%APPDATA%\Tirut\Tirut PDF\` (paste that in the address bar).
3. Delete `license.key` (if present) and open `trial.json`; set `first_run` to an old date
   like `"2020-01-01"`. Save.
4. Reopen the app — title shows `[Unregistered (free)]`.
- [ ] OCR now shows the **"Pro feature — Activate"** upsell instead of running.
- [ ] **Save** opens a dialog defaulting to `"<name> (Tirut unregistered).pdf"`. It will **not**
      let you overwrite the original — picking the original's name is rejected.
- [ ] The saved copy has a small grey footer watermark; **your original file is unchanged**.
- [ ] Re-activate the Pro key → watermark/upsell gone again.

## 6. If something breaks
Capture: the exact error dialog text (or a screenshot), what you clicked, and whether it was
the installer or portable. For a hard crash, run the exe from a terminal to see output:
`& "C:\Program Files\Tirut PDF\Tirut PDF.exe"` — paste any traceback back.
