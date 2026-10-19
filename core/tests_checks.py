from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.checks import check_field_encryption_key, encryption_health_summary


class FieldEncryptionSystemCheckTests(TestCase):
    def test_warns_when_key_not_set(self):
        with override_settings(FIELD_ENCRYPTION_KEY=''):
            errors = check_field_encryption_key(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'core.W001')

    def test_warns_on_malformed_key(self):
        with override_settings(FIELD_ENCRYPTION_KEY='not-a-real-fernet-key'):
            errors = check_field_encryption_key(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, 'core.W002')

    def test_clean_with_a_valid_key(self):
        from cryptography.fernet import Fernet
        valid_key = Fernet.generate_key().decode()
        with override_settings(FIELD_ENCRYPTION_KEY=valid_key):
            errors = check_field_encryption_key(None)
        self.assertEqual(errors, [])


class EncryptionHealthSummaryTests(TestCase):
    def test_summary_never_raises_on_empty_database(self):
        summary = encryption_health_summary()
        self.assertEqual(summary, {'total': 0, 'failed': 0, 'healthy': True})

    def test_settings_page_shows_encryption_health(self):
        admin = User.objects.create_user('healthpage_admin', password='pw', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse('site-settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('encryption_health', resp.context)
        self.assertTrue(resp.context['encryption_health']['healthy'])
