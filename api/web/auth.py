"""Authentication and authorization for Helix API.

JWT-based auth with bcrypt password hashing. Disabled by default
(HELIX_AUTH_DISABLED=true) for local single-user mode.

Env vars:
    HELIX_AUTH_DISABLED  — "true" to bypass auth (default: "true")
    HELIX_JWT_EXPIRY_HOURS — token lifetime in hours (default: 24)
    HELIX_SECRET_KEY — JWT signing key (reuses the encryption secret)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage.models import User

# --------------- Configuration ---------------

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_secret_key() -> str:
    key = os.environ.get("HELIX_SECRET_KEY", "")
    if not key:
        key = "helix-dev-secret-change-me"
    return key


def _get_expiry_hours() -> int:
    return int(os.environ.get("HELIX_JWT_EXPIRY_HOURS", "24"))


def is_auth_disabled() -> bool:
    return os.environ.get("HELIX_AUTH_DISABLED", "true").lower() == "true"


# --------------- Password hashing ---------------


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]  # bcrypt 72-byte limit
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")[:72]
    return bcrypt.checkpw(pw, hashed.encode("utf-8"))


# --------------- JWT ---------------


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_get_expiry_hours())
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, _get_secret_key(), algorithm="HS256")


def decode_access_token(token: str) -> str:
    """Decode JWT and return the username. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _get_secret_key(), algorithms=["HS256"])
    username: str | None = payload.get("sub")
    if username is None:
        raise jwt.InvalidTokenError("Missing subject claim")
    return username


# --------------- Pydantic schemas ---------------


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    username: str
    email: str | None


class AuthStatusResponse(BaseModel):
    auth_required: bool


# --------------- Dependencies ---------------

# Sentinel local user for when auth is disabled
_LOCAL_USER = User(id=0, username="local", hashed_password="", is_active=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """FastAPI dependency: extract and validate JWT, return User.

    When auth is disabled (default), this is overridden by get_current_user_noop
    via dependency_overrides in the app factory.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        username = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Note: we don't do a DB lookup here for performance. The JWT contains the
    # username which is sufficient for query filtering. A DB lookup would be
    # needed if we supported user deactivation with immediate token revocation.
    return User(id=0, username=username, hashed_password="", is_active=True)


async def get_current_user_noop() -> User:
    """No-op dependency: returns a fixed 'local' user when auth is disabled."""
    return _LOCAL_USER
