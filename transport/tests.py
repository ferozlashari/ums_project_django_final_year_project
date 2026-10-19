"""Tests for transport: bulk-assigning multiple students to a route/stop
in one submission (previously only one admission number at a time).
Run with: python manage.py test transport
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Faculty, Department, Program
from core.models import Profile
from registration.models import Student
from transport.models import Vehicle, Route, RouteStop, StudentTransportAssignment


class BulkAssignTransportTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        vehicle = Vehicle.objects.create(registration_no='KHI-001', capacity=40)
        self.route = Route.objects.create(name='Route 1 - Gulshan', vehicle=vehicle)
        self.stop = RouteStop.objects.create(route=self.route, name='Main Gate', pickup_time='08:00', order=1)

        def make_student(admission_no, name):
            user = User.objects.create_user(username=admission_no, password='p')
            return Student.objects.create(user=user, full_name=name, admission_no=admission_no, program=program)

        self.s1 = make_student('CS-001', 'Student One')
        self.s2 = make_student('CS-002', 'Student Two')
        self.s3 = make_student('CS-003', 'Student Three')

        admin_user = User.objects.create_user(username='transportadmin', password='p', is_staff=True, is_superuser=True)
        Profile.objects.update_or_create(user=admin_user, defaults={'role': 'admin'})
        self.admin = admin_user

    def test_bulk_assign_multiple_students_newline_separated(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transport-bulk-assign'), {
            'route': self.route.pk, 'stop': self.stop.pk,
            'admission_numbers': 'CS-001\nCS-002\nCS-003',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentTransportAssignment.objects.filter(route=self.route, is_active=True).count(), 3)
        for s in (self.s1, self.s2, self.s3):
            assignment = StudentTransportAssignment.objects.get(student=s)
            self.assertEqual(assignment.route, self.route)
            self.assertEqual(assignment.stop, self.stop)

    def test_bulk_assign_accepts_comma_separated_and_mixed_whitespace(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transport-bulk-assign'), {
            'route': self.route.pk, 'stop': '',
            'admission_numbers': ' CS-001 , CS-002,\nCS-003 ',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentTransportAssignment.objects.filter(route=self.route).count(), 3)

    def test_bulk_assign_unknown_admission_number_is_skipped_not_fatal(self):
        """One bad admission number in the batch must not block the rest -
        it should show up as a reported skip, not a crash or a silent
        all-or-nothing failure."""
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transport-bulk-assign'), {
            'route': self.route.pk, 'stop': self.stop.pk,
            'admission_numbers': 'CS-001\nNO-SUCH-STUDENT\nCS-002',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(StudentTransportAssignment.objects.filter(student=self.s1).exists())
        self.assertTrue(StudentTransportAssignment.objects.filter(student=self.s2).exists())
        self.assertFalse(StudentTransportAssignment.objects.filter(student=self.s3).exists())
        skipped = response.context['results']['skipped']
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0][0], 'NO-SUCH-STUDENT')

    def test_bulk_assign_moves_student_already_on_another_route(self):
        """A student already assigned elsewhere gets moved to the new
        route/stop (OneToOneField - a student has exactly one active
        assignment), not duplicated."""
        other_route = Route.objects.create(name='Route 2 - North Nazimabad')
        StudentTransportAssignment.objects.create(student=self.s1, route=other_route, is_active=True)

        self.client.force_login(self.admin)
        self.client.post(reverse('transport-bulk-assign'), {
            'route': self.route.pk, 'stop': self.stop.pk,
            'admission_numbers': 'CS-001',
        })
        self.assertEqual(StudentTransportAssignment.objects.filter(student=self.s1).count(), 1)
        self.assertEqual(StudentTransportAssignment.objects.get(student=self.s1).route, self.route)

    def test_non_admin_cannot_bulk_assign(self):
        student_user = self.s1.user
        self.client.force_login(student_user)
        response = self.client.post(reverse('transport-bulk-assign'), {
            'route': self.route.pk, 'admission_numbers': 'CS-001',
        })
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(StudentTransportAssignment.objects.filter(student=self.s1).exists())


class StaffFullNameCapitalizationTests(TestCase):
    """Registration/seed data sometimes leaves inconsistent casing (e.g.
    'Muhammad ahmed') - Staff.full_name should always display it
    normalized, without touching the underlying User fields."""

    def _make_staff(self, first_name, last_name):
        from hr.models import Staff
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        user = User.objects.create_user(
            username=f'{first_name}{last_name}'.lower(), password='p',
            first_name=first_name, last_name=last_name,
        )
        return Staff.objects.create(user=user, employee_id=f'EMP-{first_name}', department=dept, role='lecturer')

    def test_lowercase_last_name_is_capitalized_for_display(self):
        staff = self._make_staff('Muhammad', 'ahmed')
        self.assertEqual(staff.full_name, 'Muhammad Ahmed')

    def test_all_caps_name_is_normalized_for_display(self):
        staff = self._make_staff('SARA', 'KHAN')
        self.assertEqual(staff.full_name, 'Sara Khan')

    def test_already_correct_casing_is_unchanged(self):
        staff = self._make_staff('Ayesha', 'Siddiqui')
        self.assertEqual(staff.full_name, 'Ayesha Siddiqui')

    def test_underlying_user_fields_are_not_modified(self):
        staff = self._make_staff('Muhammad', 'ahmed')
        staff.full_name  # noqa: B018 - access the property
        staff.user.refresh_from_db()
        self.assertEqual(staff.user.last_name, 'ahmed')  # untouched in the database
