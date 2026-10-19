"""Reset and verification codes must never be shown on screen in production."""
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

CONSOLE = 'django.core.mail.backends.console.EmailBackend'


class ResetCodeNotExposedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('victim', 'victim@example.com', 'S3cure-pass-123')

    @override_settings(DEBUG=False, EMAIL_BACKEND=CONSOLE)
    def test_production_without_mail_server_never_shows_code_or_link(self):
        resp = self.client.post(reverse('password_reset'), {'email': 'victim@example.com'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('/password-reset/confirm/', body)
        self.assertNotIn('Test mode', body)
        self.assertNotIn('dev_otp_code', self.client.session)

    @override_settings(DEBUG=True, EMAIL_BACKEND=CONSOLE)
    def test_local_development_still_shows_code(self):
        resp = self.client.post(reverse('password_reset'), {'email': 'victim@example.com'}, follow=True)
        self.assertContains(resp, 'Test mode')

    @override_settings(DEBUG=False, EMAIL_BACKEND=CONSOLE)
    def test_registration_without_mail_server_does_not_claim_email_was_sent(self):
        from core.otp import send_code_email
        code, ok = send_code_email(self.user, 'verify_email', 'http://testserver/x/')
        self.assertFalse(ok)

    def test_normal_mail_still_sent_with_working_backend(self):
        self.client.post(reverse('password_reset'), {'email': 'victim@example.com'})
        self.assertEqual(len(mail.outbox), 1)


class ChallanLookupThrottleTests(TestCase):
    def test_public_challan_lookup_is_rate_limited(self):
        from django.core.cache import cache
        cache.clear()
        url = reverse('verify-challan')
        for _ in range(30):
            self.assertEqual(self.client.get(url, {'challan_no': 'UMS-000000-00000'}).status_code, 200)
        resp = self.client.get(url, {'challan_no': 'UMS-000000-00000'})
        self.assertEqual(resp.status_code, 429)
        cache.clear()
