"""Logins: PBKDF2 password hashes and opaque bearer tokens kept in the database."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import SessionLocal, Token, User, now
from .settings import ADMIN_PASSWORD, TOKEN_DAYS

ROLES = ("admin", "reviewer", "preparer")
_RANK = {"preparer": 0, "reviewer": 1, "admin": 2}


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2${salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(got, h)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def issue_token(db: Session, user: User) -> str:
    t = secrets.token_urlsafe(32)
    db.add(Token(token=t, user_id=user.id))
    db.commit()
    return t


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    h = request.headers.get("authorization", "")
    tok = h[7:].strip() if h.lower().startswith("bearer ") else ""
    if not tok and request.method == "GET" and "/export/" in request.url.path:
        tok = request.query_params.get("token", "")      # download links only
    if not tok:
        raise HTTPException(401, "Please log in.")
    row = db.get(Token, tok)
    if row is None or not row.user.active:
        raise HTTPException(401, "Your session has ended. Please log in again.")
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=now().tzinfo)
    if now() - created > timedelta(days=TOKEN_DAYS):
        db.delete(row)
        db.commit()
        raise HTTPException(401, "Your session has ended. Please log in again.")
    return row.user


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if _RANK.get(user.role, -1) < _RANK[role]:
            raise HTTPException(403, f"Only a {role} can do this.")
        return user
    return dep


def ensure_admin(db: Session) -> bool:
    """First start: create admin / TAXMIND_ADMIN_PASSWORD (default admin123)."""
    if db.query(User).count():
        return False
    db.add(User(username="admin", name="Administrator", role="admin", password_hash=hash_password(ADMIN_PASSWORD)))
    db.commit()
    return True
