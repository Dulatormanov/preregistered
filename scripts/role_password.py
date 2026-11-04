"""Give a Postgres LOGIN role a new random password, without the plain text ever appearing in SQL.

Usage: python3 scripts/role_password.py triage_agent
- saves the password in the macOS keychain, as service "prereg/<role>";
- copies "ALTER ROLE <role> PASSWORD '<SCRAM verifier>';" to the clipboard.
Paste that line into the Supabase SQL editor. The editor history and the database logs
then hold only the SCRAM verifier, which cannot be used to log in. Wait 30 seconds
before logging in through the pooler.
"""
# note: macOS only (security, pbcopy); the password is briefly visible to `ps` on this Mac.
import base64
import hashlib
import hmac
import re
import secrets
import subprocess
import sys

role = sys.argv[1]
assert re.fullmatch(r"[a-z_]+", role), "role names are lower-case letters and _"
password = secrets.token_urlsafe(32)
salt = secrets.token_bytes(16)
salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
stored_key = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
server_key = hmac.digest(salted, b"Server Key", "sha256")
b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
verifier = f"SCRAM-SHA-256$4096:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"

subprocess.run(["security", "add-generic-password", "-U", "-s", f"prereg/{role}", "-a", role, "-w", password],
               check=True)
subprocess.run(["pbcopy"], input=f"ALTER ROLE {role} PASSWORD '{verifier}';".encode(), check=True)
print(f"Saved in the keychain as prereg/{role}. The ALTER ROLE line is on the clipboard.")
