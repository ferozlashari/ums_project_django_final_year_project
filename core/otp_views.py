"""Views for the emailed-code flows: verify email, forgot password, change email."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, password_validation
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_http_methods, require_POST

from . import otp


def _console_email():
    """Developer machines only (DEBUG on, no mail server) - never in production."""
    return bool(settings.DEBUG) and settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend'


def _uid_token(user):
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def send_verification(request, user):
    """Email a verification code + link. Returns (dev_code_or_None, sent_ok, error)."""
    uid, token = _uid_token(user)
    link = request.build_absolute_uri(f'/verify-email/{uid}/{token}/')
    try:
        code, ok = otp.send_code_email(user, 'verify_email', link)
    except otp.OTPError as e:
        return None, False, str(e)
    return (code if _console_email() else None), ok, ''


@require_http_methods(['GET', 'POST'])
def verify_email_code(request):
    """Enter the emailed 6-digit code to activate a newly registered account."""
    uid = request.session.get('pending_verify_user_id')
    user = User.objects.filter(pk=uid, is_active=False).first() if uid else None
    if user is None:
        messages.info(request, 'Sign in, or register first.')
        return redirect('login')
    if request.method == 'POST':
        if otp.verify(user, 'verify_email', request.POST.get('code', '')):
            user.is_active = True
            user.save(update_fields=['is_active'])
            request.session.pop('pending_verify_user_id', None)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, 'Email verified! Welcome to UMS.')
            return redirect('dashboard')
        messages.error(request, 'That code is wrong or has expired. Check the email or request a new code.')
    return render(request, 'core/verify-email-code.html', {'email': user.email})


@require_POST
def verify_email_resend(request):
    uid = request.session.get('pending_verify_user_id')
    user = User.objects.filter(pk=uid, is_active=False).first() if uid else None
    if user is None:
        return redirect('login')
    dev_code, ok, err = send_verification(request, user)
    if err:
        messages.error(request, err)
    else:
        messages.success(request, 'A new code was sent.' if ok else 'We could not send the email right now. Please try again shortly.')
        if dev_code:
            request.session['dev_otp_code'] = dev_code
    return redirect('verify-email-code')


@require_http_methods(['GET', 'POST'])
def password_reset_code(request):
    """Second half of 'forgot password': email + emailed code + new password."""
    initial_email = request.session.get('reset_email', '')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        code = request.POST.get('code', '')
        p1, p2 = request.POST.get('new_password1', ''), request.POST.get('new_password2', '')
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        error = None
        if p1 != p2:
            error = 'The two passwords do not match.'
        elif user is None:
            error = 'That code is wrong or has expired.'
        else:
            try:
                password_validation.validate_password(p1, user)
            except Exception as e:  # ValidationError with .messages
                error = ' '.join(getattr(e, 'messages', [str(e)]))
        if error is None and otp.verify(user, 'password_reset', code):
            user.set_password(p1)
            user.save()
            request.session.pop('reset_email', None)
            messages.success(request, 'Password updated. You can sign in now.')
            return redirect('login')
        messages.error(request, error or 'That code is wrong or has expired.')
        initial_email = email
    return render(request, 'core/password-reset-code.html', {
        'email': initial_email, 'dev_code': request.session.pop('dev_otp_code', None) if _console_email() else None})


@login_required
@require_http_methods(['GET', 'POST'])
def change_email_confirm(request):
    """Confirm a new email address with the code sent to that address."""
    pending = otp.current_target_email(request.user, 'change_email')
    if not pending:
        messages.info(request, 'There is no email change waiting for confirmation.')
        return redirect('edit-profile')
    if request.method == 'POST':
        if otp.verify(request.user, 'change_email', request.POST.get('code', '')):
            if User.objects.filter(email__iexact=pending).exclude(pk=request.user.pk).exists():
                messages.error(request, 'That email is already used by another account.')
                return redirect('edit-profile')
            request.user.email = pending
            request.user.save(update_fields=['email'])
            messages.success(request, 'Your email address was updated.')
            return redirect('profile')
        messages.error(request, 'That code is wrong or has expired.')
    return render(request, 'core/change-email-confirm.html', {
        'pending': pending, 'dev_code': request.session.pop('dev_otp_code', None) if _console_email() else None})
