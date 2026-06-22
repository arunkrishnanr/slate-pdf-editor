"""
Offline license-key validation + trial tracking for Tirut PDF.

Design:
  * License keys are Ed25519-signed tokens. The app embeds ONLY the public key, so a
    key can be *verified* but never *forged* without the seller's private key
    (tools/license_private_key.pem — keep secret, never ship/commit it).
  * No phone-home: validation is fully offline. A key encodes who it's for, the edition,
    an optional expiry, and a seat count, all covered by the signature.
  * Free users get a time-limited full trial; afterwards the app stays usable for basic
    editing but Pro features (OCR) lock and saved files carry a small watermark.

Key format (what you paste into Activate):
    TIRUT-<base64url(payload_json)>.<base64url(signature)>
"""

from __future__ import annotations

import base64
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import date, datetime

# --- the app's public key (verify-only). Mint keys with tools/make_license.py. ---
PUBLIC_KEY_B64 = "WMRGlW2xBAYEc6jZ2E2DMtmCwxTJHnoCF2Gs8VjNOW4="

TRIAL_DAYS = 14
KEY_PREFIX = "TIRUT-"
# Where buyers go to purchase. Change to your real checkout URL (Lemon Squeezy / Paddle / site).
PURCHASE_URL = "https://tirutpdf.com/buy"


# ---------------------------------------------------------------------------
# storage location (Qt-free so this module is unit-testable headless)
# ---------------------------------------------------------------------------
def _config_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, "Tirut", "Tirut PDF")
    os.makedirs(d, exist_ok=True)
    return d


def _license_path() -> str:
    return os.path.join(_config_dir(), "license.key")


def _trial_path() -> str:
    return os.path.join(_config_dir(), "trial.json")


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
@dataclass
class License:
    name: str
    email: str
    edition: str          # "pro"
    issued: str           # ISO date
    expires: str | None   # ISO date or None for perpetual
    seats: int
    license_id: str

    @property
    def is_expired(self) -> bool:
        if not self.expires:
            return False
        try:
            return date.today() > date.fromisoformat(self.expires)
        except ValueError:
            return True


@dataclass
class Status:
    state: str            # "pro" | "trial" | "free"
    license: License | None = None
    trial_days_left: int = 0

    @property
    def is_pro(self) -> bool:
        return self.state == "pro"

    @property
    def unlocked(self) -> bool:
        """Pro features available (Pro license or an active trial)."""
        return self.state in ("pro", "trial")

    @property
    def watermark(self) -> bool:
        """Saved/exported files should carry the unregistered watermark."""
        return self.state == "free"

    @property
    def label(self) -> str:
        if self.state == "pro":
            who = self.license.email if self.license else ""
            return f"Pro — licensed to {who}".rstrip(" —")
        if self.state == "trial":
            d = self.trial_days_left
            return f"Trial — {d} day{'s' if d != 1 else ''} left"
        return "Unregistered (free)"


# ---------------------------------------------------------------------------
# key verification
# ---------------------------------------------------------------------------
def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def parse_key(key: str) -> License:
    """Verify a license key's signature and return its License. Raises ValueError on any
    problem (bad format, bad signature, malformed payload)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    key = (key or "").strip()
    if not key.startswith(KEY_PREFIX):
        raise ValueError("Not a Tirut license key.")
    body = key[len(KEY_PREFIX):]
    if "." not in body:
        raise ValueError("Malformed license key.")
    payload_b64, sig_b64 = body.split(".", 1)
    try:
        signature = _b64url_decode(sig_b64)
        payload_bytes = payload_b64.encode("ascii")
    except Exception:
        raise ValueError("Malformed license key.")

    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
    try:
        pub.verify(signature, payload_bytes)
    except InvalidSignature:
        raise ValueError("This license key is invalid (signature mismatch).")

    try:
        data = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise ValueError("Malformed license payload.")

    return License(
        name=str(data.get("name", "")),
        email=str(data.get("email", "")),
        edition=str(data.get("edition", "pro")),
        issued=str(data.get("issued", "")),
        expires=(data.get("expires") or None),
        seats=int(data.get("seats", 1)),
        license_id=str(data.get("id", "")),
    )


# ---------------------------------------------------------------------------
# activation + trial
# ---------------------------------------------------------------------------
def activate(key: str) -> License:
    """Validate and persist a key. Raises ValueError if invalid or expired."""
    lic = parse_key(key)
    if lic.is_expired:
        raise ValueError(f"This license expired on {lic.expires}.")
    with open(_license_path(), "w", encoding="utf-8") as f:
        f.write(key.strip())
    return lic


def deactivate() -> None:
    try:
        os.remove(_license_path())
    except FileNotFoundError:
        pass


def _stored_license() -> License | None:
    try:
        with open(_license_path(), encoding="utf-8") as f:
            key = f.read()
    except FileNotFoundError:
        return None
    try:
        lic = parse_key(key)
    except ValueError:
        return None
    return None if lic.is_expired else lic


def _trial_days_left() -> int:
    """Days remaining in the trial; starts the clock on first call. Clamped at 0."""
    path = _trial_path()
    try:
        with open(path, encoding="utf-8") as f:
            first = date.fromisoformat(json.load(f)["first_run"])
    except Exception:
        first = date.today()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"first_run": first.isoformat()}, f)
        except OSError:
            pass
    used = (date.today() - first).days
    return max(0, TRIAL_DAYS - used)


def status() -> Status:
    """Current entitlement: Pro (valid license) > Trial (within window) > Free."""
    lic = _stored_license()
    if lic is not None:
        return Status("pro", license=lic)
    left = _trial_days_left()
    if left > 0:
        return Status("trial", trial_days_left=left)
    return Status("free")
