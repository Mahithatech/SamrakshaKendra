
"""Admin and public user authentication routes."""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_security import (
    TOKEN_MINUTES,
    create_access_token,
    hash_password,
    require_auth,
    verify_password,
)
from app.database import get_db
from app.models import User

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

router = APIRouter(prefix="/auth", tags=["Authentication"])

_attempt_lock = threading.Lock()
_attempts: dict[str, list[float]] = defaultdict(list)

FAILURE_WINDOW_SECONDS = 600
MAX_FAILURES = 5


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    state: str = Field(min_length=2, max_length=100)
    district: str = Field(min_length=2, max_length=100)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        return value


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


def _register_failure(client_ip: str) -> None:
    now = time.time()
    with _attempt_lock:
        _attempts[client_ip] = [
            t for t in _attempts[client_ip]
            if now - t < FAILURE_WINDOW_SECONDS
        ]
        _attempts[client_ip].append(now)


def _is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    with _attempt_lock:
        _attempts[client_ip] = [
            t for t in _attempts[client_ip]
            if now - t < FAILURE_WINDOW_SECONDS
        ]
        return len(_attempts[client_ip]) >= MAX_FAILURES


@router.post("/register", summary="Register a new public user")
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    email = payload.email

    existing_user = db.query(User).filter(
        func.lower(User.email) == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        )

    user = User(
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        state=payload.state.strip(),
        district=payload.district.strip(),
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Could not create account. This email may already be registered.",
        )

    return {
        "message": "Registration successful",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "state": user.state,
            "district": user.district,
        },
    }


@router.post("/user/login", summary="Sign in as a registered user")
def user_login(
    payload: UserLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Wait 10 minutes and retry.",
        )

    email = payload.email.strip().lower()

    user = db.query(User).filter(
        func.lower(User.email) == email
    ).first()

    if not user or not verify_password(
        payload.password,
        user.password_hash,
    ):
        _register_failure(client_ip)
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    with _attempt_lock:
        _attempts.pop(client_ip, None)

    return {
        "access_token": create_access_token(user.email, role="user"),
        "token_type": "bearer",
        "expires_in": TOKEN_MINUTES * 60,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "state": user.state,
            "district": user.district,
        },
    }


@router.post("/login", summary="Admin sign in")
def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"

    if _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Wait 10 minutes and retry.",
        )

    expected_user = os.getenv("SK_ADMIN_USERNAME", "")
    password_hash = os.getenv("SK_ADMIN_PASSWORD_HASH", "")

    if (
        not expected_user
        or not password_hash
        or len(os.getenv("SK_JWT_SECRET", "")) < 40
    ):
        raise HTTPException(
            status_code=503,
            detail="Admin login is not configured. Run backend/setup_auth.py and restart the server.",
        )

    user_ok = hmac.compare_digest(payload.username, expected_user)
    password_ok = verify_password(payload.password, password_hash)

    if not (user_ok and password_ok):
        _register_failure(client_ip)
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    with _attempt_lock:
        _attempts.pop(client_ip, None)

    return {
        "access_token": create_access_token(expected_user, role="admin"),
        "token_type": "bearer",
        "expires_in": TOKEN_MINUTES * 60,
        "username": expected_user,
        "role": "admin",
    }

@router.get("/me", summary="Get current signed-in account")
def current_user(
    user: dict[str, str] = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if user["role"] == "user":
        account = db.query(User).filter(
            func.lower(User.email) == user["username"].strip().lower()
        ).first()

        if not account:
            raise HTTPException(
                status_code=404,
                detail="Registered user account not found",
            )

        return {
            "username": account.email,
            "role": "user",
            "full_name": account.full_name,
            "email": account.email,
            "state": account.state,
            "district": account.district,
            "authenticated": True,
        }

    return {
        "username": user["username"],
        "role": "admin",
        "authenticated": True,
    }