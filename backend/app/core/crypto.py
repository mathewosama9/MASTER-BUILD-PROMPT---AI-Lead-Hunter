import base64
import hashlib
import re

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.encryption_key
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    parts = [v for v in re.split(r"[\s,;]+", value) if v]
    if len(parts) > 1:  # several keys in one credential (e.g. Brave): mask each
        return ", ".join(m for v in parts if (m := mask_secret(v)))
    return f"********{value[-4:]}" if len(value) > 8 else "********"
