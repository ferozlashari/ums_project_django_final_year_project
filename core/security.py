"""
Project-wide encryption helpers.

Any model field that stores sensitive data (chat transcripts, national ID
numbers, bank/fee account numbers, etc.) can use `EncryptedTextField` below so
the value is encrypted with AES (via Fernet) before it ever reaches the
database, and transparently decrypted when read back through the ORM.

Configuration
-------------
Set FIELD_ENCRYPTION_KEY in your .env file. Generate one with:

    python manage.py generate_encryption_key

If the variable is not set, a deterministic development-only key is derived
from SECRET_KEY so the project still runs out of the box - replace it in any
real deployment.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _derive_fallback_key(secret: str) -> bytes:
    """Build a valid 32-byte urlsafe-base64 Fernet key from SECRET_KEY.

    Used only when FIELD_ENCRYPTION_KEY has not been configured, so a fresh
    checkout still works. Production deployments should always set an
    explicit FIELD_ENCRYPTION_KEY.
    """
    digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None) or os.environ.get('FIELD_ENCRYPTION_KEY')
    if key:
        if isinstance(key, str):
            key = key.encode('utf-8')
    else:
        key = _derive_fallback_key(settings.SECRET_KEY)
    return Fernet(key)


def encrypt_text(plain: str) -> str:
    if plain is None:
        return plain
    f = get_fernet()
    token = f.encrypt(plain.encode('utf-8'))
    return token.decode('utf-8')


def decrypt_text(token: str) -> str:
    if token is None:
        return token
    f = get_fernet()
    try:
        return f.decrypt(token.encode('utf-8')).decode('utf-8')
    except (InvalidToken, ValueError):
        # Value was stored before encryption was enabled, or key changed -
        # fail safe by returning the raw value instead of crashing the page.
        return token


class EncryptedTextField(models.TextField):
    """A TextField that transparently encrypts/decrypts its value at rest."""

    description = "Text encrypted at rest with Fernet (AES-128-CBC + HMAC)"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt_text(value)

    def to_python(self, value):
        return value

    def get_prep_value(self, value):
        if value is None:
            return value
        return encrypt_text(str(value))
