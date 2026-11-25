
"""JWT and Argon2 authentication helpers for Samraksha Kendra."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, HTTPException
from pwdlib import PasswordHash
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

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
        raise RuntimeError(
            "SK_JWT_SECRET is not configured. Run backend/setup_auth.py."
        )
    return secret


def create_access_token(username: str, role: str = "admin") -> str:
    if role not in {"admin", "user"}:
        raise ValueError("Invalid account role")

    now = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_MINUTES),
    }

    return jwt.encode(
        payload,
        _secret_key(),
        algorithm="HS256"
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(
            token,
            _secret_key(),
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )

        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            return None

        # Older tokens were issued only through the admin login.
        role = claims.get("role", "admin")

        if role not in {"admin", "user"}:
            return None

        claims["role"] = role
        return claims

    except Exception:
        return None


def require_auth(
    authorization: str | None = Header(default=None)
) -> dict[str, str]:

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")

    claims = (
        decode_access_token(token.strip())
        if scheme.lower() == "bearer"
        else None
    )

    if not claims:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "username": claims["sub"],
        "role": claims["role"],
    }


def require_admin_auth(
    user: dict[str, str] = None,
) -> dict[str, str]:
    # Admin authorization is enforced by the HTTP middleware.
    # This helper is available for routes needing explicit admin checks.
    if not user or user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    return user
