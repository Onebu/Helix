"""Authentication endpoints: register, login, me, status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.storage.models import User
from api.web.auth import (
    AuthStatusResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
    create_access_token,
    get_current_user,
    hash_password,
    is_auth_disabled,
    verify_password,
)
from api.web.deps import _get_session_factory

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    session_factory: async_sessionmaker = Depends(_get_session_factory),
) -> TokenResponse:
    """Register a new user and return a JWT."""
    if is_auth_disabled():
        raise HTTPException(status_code=400, detail="Authentication is disabled")

    async with session_factory() as session:
        existing = await session.execute(
            select(User).where(User.username == body.username)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Username already taken")

        user = User(
            username=body.username,
            email=body.email,
            hashed_password=hash_password(body.password),
        )
        session.add(user)
        await session.commit()

    token = create_access_token(body.username)
    return TokenResponse(access_token=token, username=body.username)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session_factory: async_sessionmaker = Depends(_get_session_factory),
) -> TokenResponse:
    """Authenticate and return a JWT."""
    if is_auth_disabled():
        raise HTTPException(status_code=400, detail="Authentication is disabled")

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == body.username)
        )
        user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")

    token = create_access_token(user.username)
    return TokenResponse(access_token=token, username=user.username)


@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(get_current_user)) -> UserInfo:
    """Return the current authenticated user's info."""
    return UserInfo(username=user.username, email=user.email)


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    """Return whether authentication is required (public endpoint)."""
    return AuthStatusResponse(auth_required=not is_auth_disabled())
