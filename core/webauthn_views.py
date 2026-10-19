"""
WebAuthn-based two-factor authentication (fingerprint / face / security key).

This delegates entirely to the device's own biometric hardware (Windows
Hello, Touch ID, Android fingerprint, etc.) via the browser's built-in
WebAuthn API - the server only ever sees a public key and a random
credential ID, never any biometric data itself. That's the same mechanism
behind "passkeys" on major sites, and it's the only honest way for a web
app to use "fingerprint/face" login without fabricating fake biometric
processing.

Entirely opt-in: a user must explicitly register a device in Account
Settings and turn the toggle on. Nobody is forced into it, and it can be
turned back off (or a device removed) at any time.
"""
import base64
import json

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from .models import WebAuthnCredential, Profile


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def _from_b64u(data: str) -> bytes:
    padded = data + '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


# ---------------------------------------------------------------------- #
# Registration (adding a fingerprint/face credential from Account Settings)
# ---------------------------------------------------------------------- #

@login_required
@require_POST
def webauthn_register_begin(request):
    existing = [
        PublicKeyCredentialDescriptor(id=_from_b64u(c.credential_id))
        for c in request.user.webauthn_credentials.all()
    ]
    options = webauthn.generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_name=request.user.username,
        user_display_name=request.user.get_full_name() or request.user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,  # forces biometric/PIN, not just "insert key"
        ),
        exclude_credentials=existing,
    )
    request.session['webauthn_reg_challenge'] = _b64u(options.challenge)
    return JsonResponse(json.loads(webauthn.options_to_json(options)))


@login_required
@require_POST
def webauthn_register_complete(request):
    try:
        body = json.loads(request.body)
        device_name = body.pop('device_name', 'My device') or 'My device'
        challenge = request.session.get('webauthn_reg_challenge')
        if not challenge:
            return JsonResponse({'error': 'Registration session expired - try again.'}, status=400)

        verification = webauthn.verify_registration_response(
            credential=body,
            expected_challenge=_from_b64u(challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
        WebAuthnCredential.objects.create(
            user=request.user,
            credential_id=_b64u(verification.credential_id),
            public_key=_b64u(verification.credential_public_key),
            sign_count=verification.sign_count,
            device_name=device_name[:100],
        )
        del request.session['webauthn_reg_challenge']
        return JsonResponse({'success': True})
    except Exception:
        return JsonResponse({'error': 'Could not register this device. Please try again.'}, status=400)


@login_required
@require_POST
def webauthn_device_delete(request, pk):
    request.user.webauthn_credentials.filter(pk=pk).delete()
    if not request.user.webauthn_credentials.exists():
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.two_factor_enabled = False
        profile.save(update_fields=['two_factor_enabled'])
    messages.success(request, 'Device removed.')
    return redirect('account-settings')


@login_required
@require_POST
def webauthn_toggle(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.two_factor_enabled and not request.user.webauthn_credentials.exists():
        messages.error(request, 'Register a passkey first.')
        return redirect('account-settings')
    profile.two_factor_enabled = not profile.two_factor_enabled
    profile.save(update_fields=['two_factor_enabled'])
    messages.success(request, 'Two-factor login enabled.' if profile.two_factor_enabled else 'Two-factor login disabled.')
    return redirect('account-settings')


# ---------------------------------------------------------------------- #
# Login-time verification (after correct password, before session starts)
# ---------------------------------------------------------------------- #

def verify_2fa_page(request):
    if not request.session.get('pending_2fa_user_id'):
        return redirect('login')
    return render(request, 'core/verify-2fa.html')


@require_POST
def webauthn_login_begin(request):
    user_id = request.session.get('pending_2fa_user_id')
    if not user_id:
        return JsonResponse({'error': 'No pending login.'}, status=400)
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return JsonResponse({'error': 'No pending login.'}, status=400)

    allow_credentials = [
        PublicKeyCredentialDescriptor(id=_from_b64u(c.credential_id))
        for c in user.webauthn_credentials.all()
    ]
    options = webauthn.generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    request.session['webauthn_auth_challenge'] = _b64u(options.challenge)
    return JsonResponse(json.loads(webauthn.options_to_json(options)))


@require_POST
def webauthn_login_complete(request):
    user_id = request.session.get('pending_2fa_user_id')
    if not user_id:
        return JsonResponse({'error': 'No pending login.'}, status=400)
    user = User.objects.filter(pk=user_id).first()
    if not user:
        return JsonResponse({'error': 'No pending login.'}, status=400)

    try:
        body = json.loads(request.body)
        raw_id = body.get('rawId') or body.get('id')
        credential = user.webauthn_credentials.filter(credential_id=raw_id).first()
        if not credential:
            return JsonResponse({'error': 'Unrecognized device.'}, status=400)

        challenge = request.session.get('webauthn_auth_challenge')
        verification = webauthn.verify_authentication_response(
            credential=body,
            expected_challenge=_from_b64u(challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=_from_b64u(credential.public_key),
            credential_current_sign_count=credential.sign_count,
        )
        credential.sign_count = verification.new_sign_count
        from django.utils import timezone
        credential.last_used_at = timezone.now()
        credential.save(update_fields=['sign_count', 'last_used_at'])

        del request.session['pending_2fa_user_id']
        request.session.pop('webauthn_auth_challenge', None)
        auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return JsonResponse({'success': True, 'redirect': '/dashboard/'})
    except Exception:
        return JsonResponse({'error': 'Verification failed. Please try again.'}, status=400)


# ---------------------------------------------------------------------- #
# "Verify identity" flow for an *already logged-in* user - reused for
# biometric attendance / exam / online-class check-in. Distinct from the
# login flow above: no session is started here, this just proves "the
# person holding this device right now is really you" and stamps a
# short-lived session flag that the calling attendance/exam/online-class
# view checks before recording anything.
# ---------------------------------------------------------------------- #

@login_required
@require_POST
def webauthn_verify_begin(request):
    if not request.user.webauthn_credentials.exists():
        return JsonResponse({
            'error': "No passkey is registered for this account.",
            'code': 'NO_CREDENTIAL',
            'message': "No passkey is registered for this account. Set up a passkey in Security Settings first.",
        }, status=400)
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=_from_b64u(c.credential_id))
        for c in request.user.webauthn_credentials.all()
    ]
    options = webauthn.generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    request.session['webauthn_verify_challenge'] = _b64u(options.challenge)
    return JsonResponse(json.loads(webauthn.options_to_json(options)))


@login_required
@require_POST
def webauthn_verify_complete(request):
    try:
        body = json.loads(request.body)
        raw_id = body.get('rawId') or body.get('id')
        credential = request.user.webauthn_credentials.filter(credential_id=raw_id).first()
        if not credential:
            return JsonResponse({
                'error': 'Unrecognized device.', 'code': 'UNKNOWN_CREDENTIAL',
                'message': "This passkey isn't recognized for your account.",
            }, status=400)

        challenge = request.session.get('webauthn_verify_challenge')
        if not challenge:
            return JsonResponse({
                'error': 'Verification session expired - try again.', 'code': 'CHALLENGE_EXPIRED',
                'message': "Your verification session expired. Please try again.",
            }, status=400)

        verification = webauthn.verify_authentication_response(
            credential=body,
            expected_challenge=_from_b64u(challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=_from_b64u(credential.public_key),
            credential_current_sign_count=credential.sign_count,
        )
        credential.sign_count = verification.new_sign_count
        from django.utils import timezone
        credential.last_used_at = timezone.now()
        credential.save(update_fields=['sign_count', 'last_used_at'])

        request.session.pop('webauthn_verify_challenge', None)
        # 60-second window: the calling view (attendance/exam/online-class
        # check-in) must record its result within this time, so a stale
        # "verified" flag can't be replayed for an unrelated action later.
        request.session['webauthn_verified_until'] = (timezone.now() + timezone.timedelta(seconds=60)).isoformat()
        return JsonResponse({'success': True})
    except Exception:
        return JsonResponse({
            'error': 'Verification failed. Please try again.', 'code': 'VERIFICATION_FAILED',
            'message': "We couldn't verify your passkey. Please try again, or check that you're using "
                       "the same browser/device the passkey was registered on.",
        }, status=400)
