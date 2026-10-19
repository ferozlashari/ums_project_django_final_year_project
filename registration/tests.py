"""Tests for the automatic year/semester-of-study computation on Student.
Run with: python manage.py test registration
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, AcademicSession, Semester
from core.models import Profile
from registration.models import Student


class AcademicPositionTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept, duration_years=4)

        today = date.today()

        def make_semester(number, offset_days):
            session = AcademicSession.objects.create(
                year=f'202{number}', start_date=today + timedelta(days=offset_days), end_date=today + timedelta(days=offset_days + 150),
            )
            return Semester.objects.create(
                name=f'Semester {number}', session=session, semester_number=number,
                start_date=today + timedelta(days=offset_days), end_date=today + timedelta(days=offset_days + 150),
            )

        # A run of consecutive institutional semesters: 1 (2 years ago) up
        # through 5 (currently active/most recent).
        self.sem1 = make_semester(1, -900)
        self.sem2 = make_semester(2, -720)
        self.sem3 = make_semester(3, -540)
        self.sem4 = make_semester(4, -360)
        self.sem5_current = make_semester(5, -30)  # started recently, still running - "now" is within it

        user = User.objects.create_user(username='posstudent', password='p')
        self.student = Student.objects.create(user=user, full_name='Position Student', admission_no='POS-001', program=self.program)

    def test_no_admission_semester_returns_none(self):
        self.assertIsNone(self.student.current_academic_position)

    def test_admitted_in_semester_1_is_currently_in_semester_5(self):
        self.student.admission_semester = self.sem1
        self.student.save()
        position = self.student.current_academic_position
        self.assertIsNotNone(position)
        self.assertEqual(position['semester'], 5)
        self.assertEqual(position['year'], 3)
        self.assertEqual(position['total_semesters'], 8)
        self.assertFalse(position['is_final_semester'])

    def test_admitted_in_semester_4_is_currently_in_semester_2(self):
        self.student.admission_semester = self.sem4
        self.student.save()
        position = self.student.current_academic_position
        self.assertEqual(position['semester'], 2)
        self.assertEqual(position['year'], 1)

    def test_position_never_exceeds_program_duration(self):
        """A student admitted so long ago that raw elapsed-semester math
        would put them past their program's length is reported as still
        in their final semester, not semester 11 of an 8-semester degree."""
        # Program only runs 8 semesters (4 years); simulate a student
        # admitted at semester 1 with the "current" semester far beyond that.
        far_future = Semester.objects.create(
            name='Semester 20', session=self.sem5_current.session, semester_number=20,
            start_date=date.today() - timedelta(days=5), end_date=date.today() + timedelta(days=100),
        )
        self.student.admission_semester = self.sem1
        self.student.save()
        position = self.student.current_academic_position
        self.assertEqual(position['semester'], 8)
        self.assertTrue(position['is_final_semester'])

    def test_no_program_returns_none(self):
        self.student.admission_semester = self.sem1
        self.student.program = None
        self.student.save()
        self.assertIsNone(self.student.current_academic_position)

    def test_admission_semester_without_semester_number_returns_none(self):
        """Data integrity guard - never fabricate a position from a
        Semester row that doesn't actually have a semester_number set."""
        blank_semester = Semester.objects.create(
            name='Undated Semester', session=self.sem1.session, semester_number=None,
            start_date=date.today() - timedelta(days=10), end_date=date.today() + timedelta(days=10),
        )
        self.student.admission_semester = blank_semester
        self.student.save()
        self.assertIsNone(self.student.current_academic_position)


class SelfRegistrationSetsAdmissionSemesterTests(TestCase):
    """Self-registration should automatically stamp the student's
    admission_semester to whatever institutional semester is active right
    now, so current_academic_position works immediately with no manual
    admin step."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        today = date.today()
        session = AcademicSession.objects.create(year='2026', start_date=today - timedelta(days=30), end_date=today + timedelta(days=120))
        self.active_semester = Semester.objects.create(
            name='Fall 2026', session=session, semester_number=7,
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=120),
        )

    def test_self_registered_student_gets_active_semester_as_admission_semester(self):
        self.client.post(reverse('register'), {
            'full_name': 'Auto Semester Student', 'email': 'autosem@example.com',
            'username': 'autosemstudent', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-8', 'account_role': 'student', 'program': self.program.pk,
        })
        student = Student.objects.get(user__username='autosemstudent')
        self.assertEqual(student.admission_semester, self.active_semester)


class BackfillAdmissionSemesterCommandTests(TestCase):
    """Existing students created before admission_semester existed should
    get a reasonable best-effort value filled in, not stay permanently
    blank forever - the command is dry-run by default and only commits
    with --apply."""

    def setUp(self):
        from io import StringIO

        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        today = date.today()
        session1 = AcademicSession.objects.create(year='2023', start_date=today - timedelta(days=900), end_date=today - timedelta(days=750))
        self.old_semester = Semester.objects.create(
            name='Fall 2023', session=session1, semester_number=1,
            start_date=today - timedelta(days=900), end_date=today - timedelta(days=750),
        )
        session2 = AcademicSession.objects.create(year='2026', start_date=today - timedelta(days=30), end_date=today + timedelta(days=120))
        self.recent_semester = Semester.objects.create(
            name='Fall 2026', session=session2, semester_number=7,
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=120),
        )
        self.StringIO = StringIO

    def _make_student(self, username, joined_days_ago):
        user = User.objects.create_user(username=username, password='p')
        user.date_joined = timezone.now() - timedelta(days=joined_days_ago)
        user.save(update_fields=['date_joined'])
        return Student.objects.create(user=user, full_name=username, admission_no=username, program=self.program)

    def test_dry_run_does_not_modify_data(self):
        from django.core.management import call_command
        student = self._make_student('oldstudent1', joined_days_ago=800)
        call_command('backfill_admission_semester', stdout=self.StringIO())
        student.refresh_from_db()
        self.assertIsNone(student.admission_semester)

    def test_apply_sets_admission_semester_matching_join_date(self):
        from django.core.management import call_command
        student = self._make_student('oldstudent2', joined_days_ago=800)  # falls within old_semester's window
        call_command('backfill_admission_semester', '--apply', stdout=self.StringIO())
        student.refresh_from_db()
        self.assertEqual(student.admission_semester, self.old_semester)

    def test_apply_does_not_touch_students_who_already_have_one(self):
        from django.core.management import call_command
        student = self._make_student('oldstudent3', joined_days_ago=800)
        student.admission_semester = self.recent_semester
        student.save()
        call_command('backfill_admission_semester', '--apply', stdout=self.StringIO())
        student.refresh_from_db()
        self.assertEqual(student.admission_semester, self.recent_semester)  # unchanged, not overwritten

    def test_join_date_before_any_semester_is_reported_unmatched_not_guessed(self):
        from django.core.management import call_command
        student = self._make_student('oldstudent4', joined_days_ago=2000)  # before old_semester even starts
        out = self.StringIO()
        call_command('backfill_admission_semester', '--apply', stdout=out)
        student.refresh_from_db()
        self.assertIsNone(student.admission_semester)
        self.assertIn('could not be matched', out.getvalue())
