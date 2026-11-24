"""Passwords and sign-in tokens.

Passwords are stored only as Argon2 hashes (pwdlib). A successful sign-in returns a JWT (HS256)
whose subject is the user id; it is sent back as `Authorization: Bearer <token>`. The secret comes
from SKILLLENS_JWT_SECRET, or is generated once and kept in runs/jwt_secret.txt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlmodel import Session

from core.db import User
from core.i18n import msg

from .state import get_lang, get_session, state

ALGORITHM = "HS256"
TOKEN_MINUTES = 60 * 24  # one day

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: int, minutes: int = TOKEN_MINUTES) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=minutes)},
                      state.jwt_secret, algorithm=ALGORITHM)


def _user_from_token(token: str | None, session: Session) -> User | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, state.jwt_secret, algorithms=[ALGORITHM], options={"require": ["sub", "iat", "exp"]})
        user = session.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    # SQLite may give a deleted user's id to a new account; a token issued before the account
    # existed must not sign in to it.
    if user is None or int(payload["iat"]) < int(datetime.fromisoformat(user.created_at).timestamp()):
        return None
    return user


def get_current_user(token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_session),
                     lang: str = Depends(get_lang)) -> User:
    """Dependency for endpoints that need a signed-in user (401 otherwise)."""
    user = _user_from_token(token, session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg("auth.required", lang),
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def get_optional_user(token: str | None = Depends(oauth2_scheme),
                      session: Session = Depends(get_session)) -> User | None:
    """Dependency for endpoints that work for everyone but do more for a signed-in user."""
    return _user_from_token(token, session)
