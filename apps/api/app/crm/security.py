"""Password hashing (bcrypt) and JWT (HS256) helpers."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"
# bcrypt only uses the first 72 bytes; reject longer passwords instead of silently truncating.
MAX_PASSWORD_BYTES = 72
# Used to keep login timing constant when the email does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


class AuthConfigError(RuntimeError):
    pass


def hash_password(password: str) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, (password_hash or _DUMMY_HASH).encode()) and bool(password_hash)
    except ValueError:
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if secret is None or not secret.get_secret_value():
        raise AuthConfigError("JWT_SECRET is not configured")
    return secret.get_secret_value()


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,  # informational for the UI; the API always re-reads the role from the DB
        "iat": now,
        "exp": now + timedelta(minutes=get_settings().jwt_expire_minutes),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["exp"]})
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
