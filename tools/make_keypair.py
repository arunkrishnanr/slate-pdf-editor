#!/usr/bin/env python3
"""
(Re)generate the Ed25519 signing keypair for Tirut PDF licensing.

You normally run this ONCE. It writes the secret private key to
tools/license_private_key.pem (gitignored) and prints the public key to embed in
slate/licensing.py as PUBLIC_KEY_B64.

WARNING: regenerating invalidates every license key already issued, because the app
will then verify against a new public key. Only do this if the private key leaked.
"""
import base64
import os
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

PRIV_PATH = "tools/license_private_key.pem"


def main():
    if os.path.exists(PRIV_PATH) and "--force" not in sys.argv:
        sys.exit(f"{PRIV_PATH} already exists. Pass --force to overwrite (invalidates all "
                 "previously issued keys).")
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    os.makedirs("tools", exist_ok=True)
    with open(PRIV_PATH, "wb") as f:
        f.write(pem)
    os.chmod(PRIV_PATH, 0o600)
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    print("Wrote", PRIV_PATH, "(keep secret!)")
    print("Set this in slate/licensing.py:")
    print('PUBLIC_KEY_B64 = "' + base64.b64encode(pub_raw).decode() + '"')


if __name__ == "__main__":
    main()
