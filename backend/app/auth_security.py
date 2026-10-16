"""JWT and Argon2 helpers for the Samraksha Kendra reviewer login."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()
TOKEN_MINUTES = 45

def hash_password(password: str) -> str:
    return _password_hash.hash(password)

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _password_hash.verify(password, stored_hash)
    except Exception:
        return False

def _secret_key() -> str:
    secret = os.getenv("SK_JWT_SECRET", "")
    if len(secret) < 40:
        raise RuntimeError("SK_JWT_SECRET is not configured. Run backend/setup_auth.py.")
    return secret

def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {"sub": username, "iat": now, "exp": now + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(payload, _secret_key(), algorithm="HS256")

def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, _secret_key(), algorithms=["HS256"], options={"require": ["sub", "iat", "exp"]})
        return claims if isinstance(claims.get("sub"), str) and claims["sub"] else None
    except Exception:
        return None

def require_auth(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    scheme, _, token = authorization.partition(" ")
    claims = decode_access_token(token.strip()) if scheme.lower() == "bearer" else None
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    return {"username": claims["sub"]}
