"""Encryption at rest for third-party tokens (GitHub OAuth tokens, Notion tokens).

`EncryptedText` is a SQLAlchemy column type: values are Fernet-encrypted on the
way in and decrypted on the way out, so the rest of the code never sees
ciphertext. Stored values carry the `enc:v1:` prefix; a value without it is a
legacy plaintext row and is returned as-is, so upgrading needs no data
migration (run scripts/encrypt_tokens.py to rewrite legacy rows).

Key: TOKEN_ENCRYPTION_KEY (a Fernet key; comma-separate several to rotate: the
first encrypts, all decrypt). Unset = derived from SECRET_KEY, which is fine
for development and means production must set SECRET_KEY anyway.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
_fernet: MultiFernet | None = None


def _keys() -> list[bytes]:
    s = get_settings()
    if s.token_encryption_key:
        keys = [k.strip() for k in s.token_encryption_key.split(",") if k.strip()]
        if keys:
            return [k.encode() for k in keys]
    derived = hashlib.sha256(f"consensus-token-key:{s.secret_key}".encode()).digest()
    return [base64.urlsafe_b64encode(derived)]


def get_fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        _fernet = MultiFernet([Fernet(k) for k in _keys()])
    return _fernet


def reset() -> None:
    """Forget the cached key set (tests / key rotation)."""
    global _fernet
    _fernet = None


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    if is_encrypted(value):
        return value
    return PREFIX + get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    if value is None or not is_encrypted(value):
        return value  # legacy plaintext row
    try:
        return get_fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        log.error("stored token cannot be decrypted with the configured keys; treating as absent")
        return None


class EncryptedText(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
