"""Emailed one-time codes (and the matching one-click links).

Every message carries BOTH a 6-digit code and a signed link, so the user can
type the code or just click - whichever is easier. Codes are stored hashed,
expire (default 10 min), are single-use, are rate limited, and are locked
after 5 wrong guesses."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import EmailOTP

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5
RESEND_COOLDOWN_SECONDS = 30

SUBJECTS = {
    'verify_email': 'Your UMS verification code',
    'password_reset': 'Your UMS password reset code',
    'change_email': 'Confirm your new UMS email address',
}
INTRO = {
    'verify_email': 'Welcome to the University Management System. Use this code to verify your email and activate your account.',
    'password_reset': 'We received a request to reset your University Management System password.',
    'change_email': 'Use this code to confirm that this is your new email address for the University Management System.',
}


class OTPError(Exception):
    pass


def _hash(user_id, purpose, code):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f'{user_id}:{purpose}:{code}'.encode(), hashlib.sha256).hexdigest()


def issue(user, purpose, target_email=''):
    """Create a fresh code (invalidating older unused ones) and return it.
    Raises OTPError if the caller is being rate limited."""
    now = timezone.now()
    recent = EmailOTP.objects.filter(user=user, purpose=purpose, created_at__gte=now - timedelta(hours=1))
    if recent.count() >= MAX_SENDS_PER_HOUR:
        raise OTPError('Too many codes requested. Please wait a while before trying again.')
    last = recent.first()
    if last and (now - last.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise OTPError(f'Please wait {RESEND_COOLDOWN_SECONDS} seconds before requesting another code.')
    EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=now)
    code = f'{secrets.randbelow(1_000_000):06d}'
    EmailOTP.objects.create(user=user, purpose=purpose, target_email=target_email, code_hash=_hash(user.pk, purpose, code),
                            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES))
    return code


def verify(user, purpose, code):
    """True if `code` is the user's current valid code (and consumes it)."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    otp = EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).order_by('-created_at').first()
    if otp is None or otp.expires_at < timezone.now() or otp.attempts >= MAX_ATTEMPTS:
        return False
    otp.attempts += 1
    otp.save(update_fields=['attempts'])
    if len(code) != 6 or not hmac.compare_digest(otp.code_hash, _hash(user.pk, purpose, code)):
        return False
    otp.used_at = timezone.now()
    otp.save(update_fields=['used_at'])
    return True


def current_target_email(user, purpose):
    otp = EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).order_by('-created_at').first()
    return otp.target_email if otp else ''


def send_code_email(user, purpose, link, to_email=None, target_email=''):
    """Issue a code and email it together with `link`. Returns (code, sent_ok)."""
    code = issue(user, purpose, target_email=target_email)
    body = (
        f'Hi {user.get_username()},\n\n{INTRO[purpose]}\n\n'
        f'    Your code:  {code}\n\n'
        f'The code is valid for {CODE_TTL_MINUTES} minutes and can be used once.\n\n'
        f'Prefer a link? Open this instead:\n{link}\n\n'
        f"If you didn't request this, you can safely ignore this email - nothing will change.\n"
    )
    from .models import EmailLog
    recipient = to_email or user.email
    log = EmailLog.objects.create(
        to_email=recipient, subject=SUBJECTS[purpose], category=purpose, user=user, attempts=1,
        body=body.replace(code, '******'))  # never store a live code in plain text
    if not settings.DEBUG and settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
        # No mail server is configured on a live site: nothing can reach the inbox.
        log.status, log.error = 'failed', 'Email delivery is not configured on this server.'
        log.save(update_fields=['status', 'error'])
        return code, False
    try:
        send_mail(SUBJECTS[purpose], body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        log.status = 'console' if settings.EMAIL_BACKEND.endswith('console.EmailBackend') else 'sent'
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'sent_at'])
        return code, True
    except Exception as exc:
        import logging
        logging.getLogger('django.security').exception('Could not send %s email to user %s', purpose, user.pk)
        log.status, log.error = 'failed', str(exc)[:500]
        log.save(update_fields=['status', 'error'])
        return code, False
