"""
Django system checks (run automatically by `manage.py check`, and thus
also by `manage.py runserver`/`test`/`migrate` in most setups) that catch
encryption-key misconfiguration at startup instead of discovering it
later as a wall of "could not decrypt" warnings while someone browses
student records.

This deliberately only validates *configuration* (is a key set, is it
the right shape) - it does not try to detect "does this key match what
old rows were encrypted with", since that can only be known by actually
attempting a decrypt, which belongs in encryption_health_summary() below
(used by the Site Settings page), not in a fast startup check.
"""
from django.core.checks import Warning, register


@register()
def check_field_encryption_key(app_configs, **kwargs):
    from django.conf import settings

    errors = []
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '') or ''
    if not key:
        errors.append(Warning(
            'FIELD_ENCRYPTION_KEY is not set - encrypted fields (CNIC) are using a key '
            'derived from SECRET_KEY instead. If SECRET_KEY is ever regenerated (e.g. the '
            '.secret_key file is deleted or not carried over), previously-encrypted values '
            'become permanently unreadable with the new key.',
            hint='Run `python manage.py generate_encryption_key` and set FIELD_ENCRYPTION_KEY '
                 'in your .env file to a permanent value.',
            id='core.W001',
        ))
    else:
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            errors.append(Warning(
                f'FIELD_ENCRYPTION_KEY is set but is not a valid Fernet key ({len(key)} chars) - '
                'encrypted fields will fail to encrypt/decrypt.',
                hint='Run `python manage.py generate_encryption_key` and copy its exact output.',
                id='core.W002',
            ))
    return errors


def encryption_health_summary():
    """Live check used by the Site Settings / Security page: actually
    attempts to read every encrypted CNIC and reports how many fail with
    the currently configured key. Read-only - never writes, never
    displays ciphertext, and never raises even on total failure."""
    from core.encrypted_fields import is_decryption_unavailable
    from registration.models import Student
    from admissions.models import Application

    total = 0
    failed = 0
    for model in (Student, Application):
        try:
            for value in model.objects.exclude(cnic='').values_list('cnic', flat=True):
                total += 1
                if is_decryption_unavailable(value):
                    failed += 1
        except Exception:
            # Table might not exist yet on a brand-new install pre-migrate;
            # this is a diagnostic, not something that should ever 500.
            continue
    return {'total': total, 'failed': failed, 'healthy': failed == 0}
