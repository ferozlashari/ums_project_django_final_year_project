"""Reusable upload validators. Without these, every FileField in the
project would accept literally any file type at any size - including
executables - which is both a security risk and a denial-of-service vector
(someone uploading a 2GB file to a "CNIC copy" field). Applied as Django
validators so they run on every save, including via the admin and the API,
not just the specific form that happens to be in front of a user.
"""
import os

from django.core.exceptions import ValidationError

DOCUMENT_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
DOCUMENT_MAX_SIZE_MB = 5

ASSIGNMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.zip', '.jpg', '.jpeg', '.png', '.txt', '.py', '.ipynb'}
ASSIGNMENT_MAX_SIZE_MB = 20


def _validate(value, allowed_extensions, max_size_mb, kind):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f'Unsupported file type "{ext}" for {kind}. Allowed: {", ".join(sorted(allowed_extensions))}.'
        )
    max_bytes = max_size_mb * 1024 * 1024
    if value.size > max_bytes:
        raise ValidationError(f'{kind} must be under {max_size_mb}MB (this file is {value.size / 1024 / 1024:.1f}MB).')


def validate_document_upload(value):
    """CNIC copies, education certificates, medical/consent letters -
    documents, not arbitrary files. PDF or a scanned image only."""
    _validate(value, DOCUMENT_EXTENSIONS, DOCUMENT_MAX_SIZE_MB, 'this document')


def validate_assignment_upload(value):
    """Assignment submissions - a wider set of academic file types, still
    excludes executables and anything that could be a malware vector."""
    _validate(value, ASSIGNMENT_EXTENSIONS, ASSIGNMENT_MAX_SIZE_MB, 'this submission')
