"""Tests for physical biometric (fingerprint/face/RFID) check-in: honest
'Not Configured' when no device exists, a real attempt against the device
endpoint when one does, and offline/rejected never counted as present."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Department, Faculty, Program
from attendance.models import AttendanceRecord
from biometrics.models import BiometricProviderConfig, BiometricVerificationEvent
from registration.models import Student


class PhysicalBiometricTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        u = User.objects.create_user('bio1', password='pw')
        self.student = Student.objects.create(user=u, full_name='Bio One', admission_no='BIO-1', program=program)
        self.client.force_login(u)

    def test_attendance_page_shows_not_configured_when_no_device_exists(self):
        resp = self.client.get(reverse('attendance-list'))
        self.assertContains(resp, 'Fingerprint')
        self.assertContains(resp, 'Not Configured')

    def test_checkin_refused_outright_with_no_device_configured(self):
        resp = self.client.post(reverse('attendance-device-checkin', args=['fingerprint']), follow=True)
        self.assertContains(resp, 'Not Configured')
        self.assertFalse(AttendanceRecord.objects.filter(student=self.student).exists())

    def test_unreachable_device_is_reported_offline_not_faked_as_present(self):
        BiometricProviderConfig.objects.create(name='Lab Scanner', provider_type='fingerprint',
                                               endpoint='http://192.0.2.1:9', device_identifier='dev-1', is_enabled=True)
        with mock.patch('requests.post', side_effect=OSError('unreachable')):
            resp = self.client.post(reverse('attendance-device-checkin', args=['fingerprint']), follow=True)
        self.assertContains(resp, 'offline')
        self.assertFalse(AttendanceRecord.objects.filter(student=self.student, present=True).exists())
        self.assertEqual(BiometricVerificationEvent.objects.get().result, 'offline')

    def test_verified_response_marks_attendance_present(self):
        BiometricProviderConfig.objects.create(name='Lab Scanner', provider_type='face',
                                               endpoint='http://device.local', device_identifier='dev-2', is_enabled=True)
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {'verified': True, 'reference': 'evt-1'}
        fake.raise_for_status = mock.Mock()
        with mock.patch('requests.post', return_value=fake):
            self.client.post(reverse('attendance-device-checkin', args=['face']), follow=True)
        record = AttendanceRecord.objects.get(student=self.student)
        self.assertTrue(record.present)
        self.assertEqual(record.method, 'biometric_face')

    def test_rejected_response_does_not_mark_present(self):
        BiometricProviderConfig.objects.create(name='Lab Scanner', provider_type='fingerprint',
                                               endpoint='http://device.local', device_identifier='dev-3', is_enabled=True)
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {'verified': False}
        fake.raise_for_status = mock.Mock()
        with mock.patch('requests.post', return_value=fake):
            resp = self.client.post(reverse('attendance-device-checkin', args=['fingerprint']), follow=True)
        self.assertContains(resp, 'not recognised')
        self.assertFalse(AttendanceRecord.objects.exists())
