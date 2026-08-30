# -*- coding: utf-8 -*-
"""
gen_hash.py — Password Hash Generator for mepanana.extension
Run this script standalone (outside Revit) to generate HMAC-SHA256 hashes.
Copy the output hashes into lib/py/auth.py > VALID_CREDENTIALS.

Usage:
    python gen_hash.py
"""
import hashlib
import hmac
import getpass

_SECRET = b"mepanana_2024_internal_key"

def generate_hash(password):
    return hmac.new(_SECRET, password.encode("utf-8"), hashlib.sha256).hexdigest()

if __name__ == "__main__":
    print("=" * 60)
    print("  mepanana Password Hash Generator")
    print("=" * 60)
    print("Enter passwords to generate hashes.")
    print("Type 'done' when finished.\n")

    while True:
        try:
            pwd = getpass.getpass("Password (hidden): ")
        except Exception:
            pwd = raw_input("Password: ")

        if pwd.lower() == "done" or not pwd:
            break

        h = generate_hash(pwd)
        print("  Hash: {}\n".format(h))

    print("\nPaste the hashes into auth.py > VALID_CREDENTIALS dict.")
    print("Never store the plaintext passwords in code!")