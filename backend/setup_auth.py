"""Create/update local admin login settings without printing secrets."""
from __future__ import annotations

import getpass
import secrets
from pathlib import Path

from pwdlib import PasswordHash

ENV_PATH = Path(__file__).resolve().parent / ".env"
KEYS = {"SK_ADMIN_USERNAME", "SK_ADMIN_PASSWORD_HASH", "SK_JWT_SECRET"}

def main() -> None:
    if not ENV_PATH.exists():
        raise SystemExit("backend/.env was not found. Create it with the DATABASE_URL first; do not share it.")
    username = input("Choose admin username [admin]: ").strip() or "admin"
    if any(ch.isspace() for ch in username) or len(username) > 100:
        raise SystemExit("Username must be 1-100 characters with no whitespace.")
    password = getpass.getpass("Choose a unique admin password (minimum 12 characters): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords did not match. No settings were written.")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters. No settings were written.")
    hashed = PasswordHash.recommended().hash(password)
    secret = secrets.token_urlsafe(48)
    existing = ENV_PATH.read_text(encoding="utf-8").splitlines()
    kept = [line for line in existing if not any(line.strip().startswith(key + "=") for key in KEYS)]
    kept.extend([f"SK_ADMIN_USERNAME={username}", f"SK_ADMIN_PASSWORD_HASH={hashed}", f"SK_JWT_SECRET={secret}"])
    ENV_PATH.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    print("Local admin login configured successfully. Password/hash/secret were not printed.")
    print("Restart the backend before signing in. Keep backend/.env out of Git and never share it.")

if __name__ == "__main__":
    main()
