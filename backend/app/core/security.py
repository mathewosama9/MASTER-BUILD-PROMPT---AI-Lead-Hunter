import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_fingerprint(password_hash: str) -> str:
    """Short digest of the stored hash. Tokens carry it, so changing the password invalidates them."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_access_token(
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    minutes: int | None = None,
    password_hash: str | None = None,
    impersonator: uuid.UUID | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "ws": str(workspace_id),
        "iat": now,
        "exp": now + timedelta(minutes=minutes or settings.access_token_minutes),
        "jti": secrets.token_hex(8),
    }
    if password_hash:
        payload["pv"] = password_fingerprint(password_hash)
    if impersonator:
        payload["imp"] = str(impersonator)  # a platform admin viewing this account, read-only
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])


def _purpose_key(purpose: str) -> str:
    # A key per purpose: a reset link can't be used as a session or a verification link, and vice versa.
    return f"{get_settings().secret_key}:{purpose}"


def create_purpose_token(purpose: str, user_id: uuid.UUID, minutes: int, **claims: str) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=minutes), **claims}
    return jwt.encode(payload, _purpose_key(purpose), algorithm=ALGORITHM)


def decode_purpose_token(purpose: str, token: str) -> dict | None:
    """Claims of a valid, unexpired token for `purpose`; None otherwise."""
    try:
        payload = jwt.decode(token, _purpose_key(purpose), algorithms=[ALGORITHM])
        uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return payload


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def constant_time_equals(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


def hash_code(code: str) -> str:
    """One-way hash for short-lived linking codes so a DB leak does not expose live codes."""
    return hashlib.sha256((get_settings().secret_key + code).encode()).hexdigest()
