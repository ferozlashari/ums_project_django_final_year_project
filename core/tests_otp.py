"""Emailed 6-digit code + link flows: registration, forgot password, change email."""
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import otp
from core.models import EmailLog, EmailOTP

LOCMEM = dict(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')


def code_from_outbox(n=-1):
    return re.search(r'Your code:\s+(\d{6})', mail.outbox[n].body).group(1)


@override_settings(**LOCMEM)
class OTPServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u1', 'u1@example.com', 'pw12345678')

    def test_code_is_single_use_hashed_and_expires(self):
        code = otp.issue(self.user, 'password_reset')
        row = EmailOTP.objects.get()
        self.assertNotIn(code, row.code_hash)
        self.assertFalse(otp.verify(self.user, 'password_reset', '000000') and code != '000000')
        self.assertTrue(otp.verify(self.user, 'password_reset', code))
        self.assertFalse(otp.verify(self.user, 'password_reset', code))  # already used

    def test_wrong_purpose_and_expired_codes_fail(self):
        code = otp.issue(self.user, 'password_reset')
        self.assertFalse(otp.verify(self.user, 'verify_email', code))
        EmailOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(otp.verify(self.user, 'password_reset', code))

    def test_locks_after_too_many_wrong_guesses(self):
        code = otp.issue(self.user, 'password_reset')
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(otp.MAX_ATTEMPTS):
            self.assertFalse(otp.verify(self.user, 'password_reset', wrong))
        self.assertFalse(otp.verify(self.user, 'password_reset', code))  # even the right one is now locked

    def test_new_code_invalidates_old_and_resend_is_rate_limited(self):
        otp.issue(self.user, 'password_reset')
        with self.assertRaises(otp.OTPError):
            otp.issue(self.user, 'password_reset')  # cooldown
        EmailOTP.objects.update(created_at=timezone.now() - timedelta(minutes=5))
        new = otp.issue(self.user, 'password_reset')
        self.assertTrue(otp.verify(self.user, 'password_reset', new))

    def test_email_contains_code_and_link_and_log_hides_code(self):
        code, ok = otp.send_code_email(self.user, 'password_reset', 'https://x.test/link/')
        self.assertTrue(ok)
        body = mail.outbox[0].body
        self.assertIn(code, body)
        self.assertIn('https://x.test/link/', body)
        log = EmailLog.objects.get()
        self.assertEqual(log.status, 'sent')
        self.assertNotIn(code, log.body)


@override_settings(**LOCMEM)
class PasswordResetByCodeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pr', 'pr@example.com', 'OldPass!12345')

    def test_full_reset_with_code(self):
        r = self.client.post(reverse('password_reset'), {'email': 'pr@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/password-reset/confirm/', mail.outbox[0].body)   # the link is there too
        code = code_from_outbox()
        r = self.client.post(reverse('password-reset-code'), {
            'email': 'pr@example.com', 'code': code, 'new_password1': 'Brand-New-Pass-77', 'new_password2': 'Brand-New-Pass-77'})
        self.assertRedirects(r, reverse('login'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-New-Pass-77'))

    def test_wrong_code_or_weak_password_changes_nothing(self):
        self.client.post(reverse('password_reset'), {'email': 'pr@example.com'})
        code = code_from_outbox()
        bad = '000000' if code != '000000' else '111111'
        self.client.post(reverse('password-reset-code'), {'email': 'pr@example.com', 'code': bad, 'new_password1': 'Brand-New-Pass-77', 'new_password2': 'Brand-New-Pass-77'})
        self.client.post(reverse('password-reset-code'), {'email': 'pr@example.com', 'code': code, 'new_password1': '123', 'new_password2': '123'})
        self.client.post(reverse('password-reset-code'), {'email': 'pr@example.com', 'code': code, 'new_password1': 'Brand-New-Pass-77', 'new_password2': 'different-Pass-77'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass!12345'))

    def test_unknown_email_reveals_nothing_and_sends_nothing(self):
        r = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        r = self.client.post(reverse('password-reset-code'), {'email': 'nobody@example.com', 'code': '123456', 'new_password1': 'Brand-New-Pass-77', 'new_password2': 'Brand-New-Pass-77'})
        self.assertEqual(r.status_code, 200)

    def test_classic_link_still_works(self):
        self.client.post(reverse('password_reset'), {'email': 'pr@example.com'})
        link = re.search(r'https?://[^\s]+/password-reset/confirm/[^\s]+', mail.outbox[0].body).group(0)
        r = self.client.get(link.split('testserver')[-1], follow=True)
        self.assertEqual(r.status_code, 200)


@override_settings(**LOCMEM)
class RegistrationVerificationTests(TestCase):
    def _register(self):
        return self.client.post(reverse('register'), {
            'username': 'newbie', 'email': 'newbie@example.com', 'password1': 'Str0ng-Pass-991', 'password2': 'Str0ng-Pass-991',
            'full_name': 'New Bie', 'cnic': '12345-1234567-1', 'account_role': 'staff'})

    def test_register_sends_code_and_code_activates_account(self):
        self.assertEqual(self._register().status_code, 200)
        user = User.objects.get(username='newbie')
        self.assertFalse(user.is_active)
        code = code_from_outbox()
        self.assertIn('/verify-email/', mail.outbox[0].body)             # link included
        self.assertEqual(self.client.post(reverse('verify-email-code'), {'code': '000001' if code != '000001' else '000002'}).status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        r = self.client.post(reverse('verify-email-code'), {'code': code})
        self.assertRedirects(r, reverse('dashboard'), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_link_still_activates(self):
        self._register()
        link = re.search(r'/verify-email/[^\s]+', mail.outbox[0].body).group(0)
        self.client.get(link)
        self.assertTrue(User.objects.get(username='newbie').is_active)

    def test_code_page_requires_pending_registration(self):
        self.assertRedirects(self.client.get(reverse('verify-email-code')), reverse('login'), fetch_redirect_response=False)


@override_settings(**LOCMEM)
class ChangeEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ce', 'old@example.com', 'pw12345678')
        self.client.force_login(self.user)

    def test_email_changes_only_after_code_sent_to_new_address(self):
        r = self.client.post(reverse('edit-profile'), {'first_name': 'A', 'last_name': 'B', 'email': 'new@example.com'})
        self.assertRedirects(r, reverse('change-email-confirm'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.com')
        self.assertEqual(mail.outbox[0].to, ['new@example.com'])
        self.client.post(reverse('change-email-confirm'), {'code': code_from_outbox()})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
