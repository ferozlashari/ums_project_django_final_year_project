"""Transparent Fernet encryption for sensitive model fields.

The field always encrypts non-empty values before database writes. If an
explicit FIELD_ENCRYPTION_KEY is not configured, the project derives a stable
Fernet key from DJANGO_SECRET_KEY so a fresh zero-cost installation is still
safe at rest. Production deployments should set a dedicated encryption key
and keep it outside source control.
"""
from django.db import models
from .security import get_fernet


class _ProtectedUnavailable(str):
    """A str subclass (so existing template/form code that expects a plain
    string keeps working) that renders as a clear, safe placeholder rather
    than raw ciphertext when a field can't be decrypted. Never equal to any
    real value, so accidental round-trip saves are visually obvious."""
    def __new__(cls):
        return super().__new__(cls, 'Protected information unavailable')


DECRYPTION_UNAVAILABLE = _ProtectedUnavailable()


def is_decryption_unavailable(value):
    """True if `value` is the placeholder above - use this in forms/views
    before saving a field back, so the placeholder itself never gets
    persisted as if it were real data."""
    return isinstance(value, _ProtectedUnavailable)


class EncryptedCharField(models.CharField):
    """CharField encrypted at rest while retaining normal Django form/admin use."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 500)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        if isinstance(value, str) and value.startswith('gAAAAA'):
            return value
        return get_fernet().encrypt(str(value).encode('utf-8')).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return value
        if not str(value).startswith('gAAAAA'):
            # Backward compatibility for records created before encryption was enabled.
            return value
        try:
            return get_fernet().decrypt(str(value).encode('utf-8')).decode('utf-8')
        except Exception:
            import logging
            logging.getLogger('django.security').warning(
                'EncryptedCharField could not decrypt a stored value (field=%s) - '
                'FIELD_ENCRYPTION_KEY likely changed since this row was written.',
                self.name,
            )
            # Never return raw ciphertext to callers - a template that forgot
            # to special-case this would otherwise display garbled encrypted
            # bytes to an end user. Surface a clearly-marked placeholder
            # instead; the warning above is what actually gets this fixed.
            return DECRYPTION_UNAVAILABLE

    def to_python(self, value):
        return value
