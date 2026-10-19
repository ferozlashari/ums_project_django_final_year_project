"""Tests for hostel: gender-matched room availability, required document
uploads, and the apply flow's automatic fee-challan generation.
Run with: python manage.py test hostel
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from academics.models import Faculty, Department, Program
from registration.models import Student
from hostel.models import Room, HostelApplication, Hostel
from finance.models import Invoice


def _fake_pdf(name='cnic.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4 fake test file', content_type='application/pdf')


class HostelAvailabilityTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        self.hostel = Hostel.objects.create(name='Test Hostel', gender='male')
        self.room = Room.objects.create(hostel=self.hostel, block='A', number='101', room_type='shared', capacity=2)

    def _make_student(self, username, admission_no, gender='male'):
        user = User.objects.create_user(username=username, password='p')
        return Student.objects.create(user=user, full_name=username, admission_no=admission_no, program=self.program, gender=gender)

    def test_room_not_full_when_empty(self):
        self.assertEqual(self.room.occupied_count, 0)
        self.assertFalse(self.room.is_full)

    def test_room_becomes_full_at_capacity(self):
        s1 = self._make_student('res1', 'UMS-H-001')
        s2 = self._make_student('res2', 'UMS-H-002')
        HostelApplication.objects.create(student=s1, hostel=self.hostel, assigned_room=self.room, status='approved', cnic_copy=_fake_pdf())
        HostelApplication.objects.create(student=s2, hostel=self.hostel, assigned_room=self.room, status='approved', cnic_copy=_fake_pdf())
        self.assertEqual(self.room.occupied_count, 2)
        self.assertTrue(self.room.is_full)

    def test_apply_page_shows_availability_without_error(self):
        student = self._make_student('applicant1', 'UMS-H-003')
        self.client.force_login(student.user)
        response = self.client.get(reverse('hostel-apply'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Room Type Availability', response.content)

    def test_opposite_gender_hostel_not_shown(self):
        """A male student must never see the girls' hostel as an option."""
        girls_hostel = Hostel.objects.create(name="Girls' Hostel", gender='female')
        student = self._make_student('maleapplicant', 'UMS-H-004', gender='male')
        self.client.force_login(student.user)
        response = self.client.get(reverse('hostel-apply'))
        self.assertNotIn(girls_hostel.name.encode(), response.content)

    def test_apply_blocked_without_gender_set(self):
        user = User.objects.create_user(username='nogender', password='p')
        student = Student.objects.create(user=user, full_name='No Gender', admission_no='UMS-H-005', program=self.program)
        self.client.force_login(user)
        response = self.client.get(reverse('hostel-apply'))
        self.assertEqual(response.status_code, 302)


class HostelApplicationFlowTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        self.hostel = Hostel.objects.create(name='Test Hostel', gender='male')
        user = User.objects.create_user(username='hostelapplicant', password='p')
        self.student = Student.objects.create(user=user, full_name='Hostel Applicant', admission_no='UMS-H-100', program=self.program, gender='male')

    def test_apply_requires_cnic_document(self):
        self.client.force_login(self.student.user)
        self.client.post(reverse('hostel-apply'), {'hostel': self.hostel.id, 'room_type_preference': 'shared'})
        self.assertFalse(HostelApplication.objects.filter(student=self.student).exists())

    def test_apply_generates_fee_challan(self):
        self.client.force_login(self.student.user)
        response = self.client.post(reverse('hostel-apply'), {
            'hostel': self.hostel.id, 'room_type_preference': 'shared', 'cnic_copy': _fake_pdf(),
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(HostelApplication.objects.filter(student=self.student).exists())
        self.assertTrue(Invoice.objects.filter(student=self.student, category='hostel').exists())

    def test_cannot_apply_twice(self):
        HostelApplication.objects.create(student=self.student, hostel=self.hostel, status='pending', cnic_copy=_fake_pdf())
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('hostel-apply'))
        self.assertEqual(response.status_code, 302)
