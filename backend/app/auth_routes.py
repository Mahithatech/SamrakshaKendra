"""Restricted admin sign-in endpoints. No public registration is provided."""
from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth_security import TOKEN_MINUTES, create_access_token, require_auth, verify_password
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

def _register_failure(client_ip: str) -> None:
    now = time.time()
    with _attempt_lock:
        _attempts[client_ip] = [t for t in _attempts[client_ip] if now - t < FAILURE_WINDOW_SECONDS]
        _attempts[client_ip].append(now)

def _is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    with _attempt_lock:
        _attempts[client_ip] = [t for t in _attempts[client_ip] if now - t < FAILURE_WINDOW_SECONDS]
        return len(_attempts[client_ip]) >= MAX_FAILURES

@router.post("/login", summary="Sign in to Samraksha Kendra")
def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait 10 minutes and retry.")
    expected_user = os.getenv("SK_ADMIN_USERNAME", "")
    password_hash = os.getenv("SK_ADMIN_PASSWORD_HASH", "")
    if not expected_user or not password_hash or len(os.getenv("SK_JWT_SECRET", "")) < 40:
        raise HTTPException(status_code=503, detail="Admin login is not configured. Run backend/setup_auth.py and restart the server.")
    user_ok = hmac.compare_digest(payload.username, expected_user)
    password_ok = verify_password(payload.password, password_hash)
    if not (user_ok and password_ok):
        _register_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    with _attempt_lock:
        _attempts.pop(client_ip, None)
    return {"access_token": create_access_token(expected_user), "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60, "username": expected_user}

@router.get("/me", summary="Get current signed-in user")
def current_user(user: dict[str, str] = Depends(require_auth)):
    return {"username": user["username"], "authenticated": True}
