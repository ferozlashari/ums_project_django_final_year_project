"""Tests for the Biometric Command Center: honest empty state, real device
status derived from last_seen_at (never fabricated), and real today's event
counts."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Department, Faculty, Program
from biometrics.models import BiometricProviderConfig, BiometricVerificationEvent
from registration.models import Student


class CommandCenterTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        u = User.objects.create_user('cc_stu', password='pw')
        self.student = Student.objects.create(user=u, full_name='CC Student', admission_no='CC-1', program=program)
        self.admin = User.objects.create_user('cc_admin', password='pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_empty_state_when_no_devices_configured(self):
        resp = self.client.get(reverse('biometric-command-center'))
        self.assertContains(resp, 'No biometric devices configured.')

    def test_non_admin_cannot_view(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('biometric-command-center'))
        self.assertNotEqual(resp.status_code, 200)

    def test_recently_seen_device_shows_online_stale_device_shows_offline(self):
        BiometricProviderConfig.objects.create(name='Gate Scanner', provider_type='fingerprint',
                                               device_identifier='dev-a', is_enabled=True,
                                               last_seen_at=timezone.now() - datetime.timedelta(minutes=2))
        BiometricProviderConfig.objects.create(name='Old Terminal', provider_type='face',
                                               device_identifier='dev-b', is_enabled=True,
                                               last_seen_at=timezone.now() - datetime.timedelta(hours=5))
        BiometricProviderConfig.objects.create(name='New Reader', provider_type='rfid',
                                               device_identifier='dev-c', is_enabled=True, last_seen_at=None)
        resp = self.client.get(reverse('biometric-command-center'))
        content = resp.content.decode()
        self.assertIn('Online', content)
        self.assertIn('Offline', content)
        self.assertIn('Never contacted', content)

    def test_todays_event_counts_are_real_and_scoped_to_today(self):
        device = BiometricProviderConfig.objects.create(name='Gate', provider_type='fingerprint', device_identifier='dev-d', is_enabled=True)
        BiometricVerificationEvent.objects.create(provider=device, student=self.student, result='verified', captured_at=timezone.now())
        BiometricVerificationEvent.objects.create(provider=device, student=self.student, result='verified', captured_at=timezone.now())
        BiometricVerificationEvent.objects.create(provider=device, student=self.student, result='rejected', captured_at=timezone.now())
        BiometricVerificationEvent.objects.create(provider=device, student=self.student, result='verified',
                                                  captured_at=timezone.now() - datetime.timedelta(days=2))
        resp = self.client.get(reverse('biometric-command-center'))
        self.assertEqual(resp.context['event_counts']['verified'], 2)
        self.assertEqual(resp.context['event_counts']['rejected'], 1)


class AdminRegistrationTests(TestCase):
    """Regression test for the exact bug reported: the "+ Add Device" link
    on the Command Center pointed at a Django Admin page that never existed
    because BiometricProviderConfig was not registered."""

    def test_biometric_provider_config_add_page_exists_in_django_admin(self):
        admin = User.objects.create_superuser('admin_bio_reg', 'a@example.com', 'pw')
        self.client.force_login(admin)
        resp = self.client.get('/admin/biometrics/biometricproviderconfig/add/')
        self.assertEqual(resp.status_code, 200)

    def test_biometric_verification_events_are_visible_but_not_hand_creatable(self):
        admin = User.objects.create_superuser('admin_bio_reg2', 'b@example.com', 'pw')
        self.client.force_login(admin)
        list_resp = self.client.get('/admin/biometrics/biometricverificationevent/')
        self.assertEqual(list_resp.status_code, 200)
        add_resp = self.client.get('/admin/biometrics/biometricverificationevent/add/')
        self.assertEqual(add_resp.status_code, 403)
