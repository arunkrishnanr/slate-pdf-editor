#!/usr/bin/env python3
"""
Mint a Tirut PDF license key for a buyer.

Keep tools/license_private_key.pem SECRET — anyone with it can forge keys.
Never commit it, never ship it inside the app.

Usage:
    python tools/make_license.py --name "Jane Doe" --email jane@acme.com
    python tools/make_license.py --email jane@acme.com --seats 5 --expires 2027-06-22

Give the printed TIRUT-… key to the buyer; they paste it into Help → Activate License.
"""
import argparse
import base64
import json
import secrets
import sys
from datetime import date

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

PRIV_PATH = "tools/license_private_key.pem"


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def main():
    ap = argparse.ArgumentParser(description="Mint a Tirut PDF license key.")
    ap.add_argument("--name", default="")
    ap.add_argument("--email", required=True)
    ap.add_argument("--seats", type=int, default=1, help="devices allowed (informational)")
    ap.add_argument("--expires", default=None, help="ISO date YYYY-MM-DD; omit for perpetual")
    ap.add_argument("--edition", default="pro")
    args = ap.parse_args()

    if args.expires:
        try:
            date.fromisoformat(args.expires)
        except ValueError:
            sys.exit("--expires must be YYYY-MM-DD")

    try:
        with open(PRIV_PATH, "rb") as f:
            priv = serialization.load_pem_private_key(f.read(), password=None)
    except FileNotFoundError:
        sys.exit(f"Private key not found at {PRIV_PATH}. Run tools/make_keypair.py first.")
    if not isinstance(priv, Ed25519PrivateKey):
        sys.exit("Private key is not Ed25519.")

    payload = {
        "name": args.name,
        "email": args.email,
        "edition": args.edition,
        "issued": date.today().isoformat(),
        "expires": args.expires,
        "seats": args.seats,
        "id": secrets.token_hex(8),
    }
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = priv.sign(payload_b64.encode("ascii"))
    key = f"TIRUT-{payload_b64}.{b64url(signature)}"

    print("License for:", args.email, f"({args.edition}, {args.seats} seat(s),",
          f"expires {args.expires or 'never'})")
    print(key)


if __name__ == "__main__":
    main()
