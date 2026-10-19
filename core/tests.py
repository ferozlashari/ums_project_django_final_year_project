"""Tests for core: automatic Profile creation, role-based access control,
and the public registration flow. Run with: python manage.py test core
"""
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from core.models import Profile


class ProfileSignalTests(TestCase):
    """The post_save signal (core/signals.py) must give every User a
    Profile automatically, regardless of how the User was created - this
    replaces the manual Profile.objects.create() calls that used to cause
    IntegrityErrors on double-submission."""

    def test_plain_user_gets_student_profile_by_default(self):
        user = User.objects.create_user(username='newperson', password='pass12345')
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.role, 'student')

    def test_staff_flag_user_gets_restricted_staff_profile_not_admin(self):
        # only a superuser starts as 'admin'; a login that merely has the is_staff flag must not.
        user = User.objects.create_user(username='staffer', password='pass12345', is_staff=True)
        self.assertEqual(user.profile.role, 'staff')

    def test_superuser_gets_admin_profile(self):
        user = User.objects.create_superuser(username='root', password='pass12345', email='root@example.com')
        self.assertEqual(user.profile.role, 'admin')

    def test_signal_never_creates_duplicate_profile(self):
        """Saving the same user twice (e.g. an admin edit) must not error -
        this is the exact bug class that broke /register/ in production."""
        user = User.objects.create_user(username='resaved', password='pass12345')
        user.first_name = 'Updated'
        user.save()  # second post_save fire - must not raise IntegrityError
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)


class RegistrationFlowTests(TestCase):
    """The public /register/ view: successful signup, and that a duplicate
    submission fails gracefully with a message instead of a 500 crash
    (this is the IntegrityError bug found via screenshot earlier)."""

    def setUp(self):
        self.client = Client()
        from academics.models import Faculty, Department, Program
        faculty = Faculty.objects.create(name='Test Faculty')
        dept = Department.objects.create(name='Test Department', faculty=faculty)
        self.program = Program.objects.create(name='Test Program', code='TP', department=dept)

    def test_register_creates_inactive_user_pending_verification(self):
        response = self.client.post(reverse('register'), {
            'full_name': 'Test Student', 'email': 'teststudent@example.com',
            'username': 'teststudent', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-1', 'account_role': 'student', 'program': self.program.pk,
        })
        self.assertEqual(response.status_code, 200)  # renders verify-email-sent page
        user = User.objects.get(username='teststudent')
        self.assertFalse(user.is_active)  # must verify email first
        self.assertEqual(user.profile.role, 'student')
        self.assertEqual(user.student_profile.program, self.program)

    def test_register_as_student_requires_program(self):
        """A student signup with no program selected must be rejected with
        a clear form error, not silently create an incomplete Student
        record that can never register for courses."""
        response = self.client.post(reverse('register'), {
            'full_name': 'No Program Student', 'email': 'noprogram@example.com',
            'username': 'noprogramstudent', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-9', 'account_role': 'student',
        })
        self.assertEqual(response.status_code, 200)  # re-renders the form with an error
        self.assertFalse(User.objects.filter(username='noprogramstudent').exists())

    def test_duplicate_registration_does_not_crash(self):
        """Submitting the same form twice must show a friendly error, not a
        raw IntegrityError traceback."""
        payload = {
            'full_name': 'Dup User', 'email': 'dup@example.com',
            'username': 'dupuser', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-2', 'account_role': 'student', 'program': self.program.pk,
        }
        self.client.post(reverse('register'), payload)
        # Second submission with the same username should not 500.
        response = self.client.post(reverse('register'), payload)
        self.assertIn(response.status_code, (200, 302))

    def test_register_as_guardian_creates_guardian_role_not_staff(self):
        """Parent/Guardian is a real, selectable account type - previously
        there was no way to self-register as one at all (only Student and
        Faculty checkboxes existed; leaving both unchecked silently made
        you Staff with no confirmation)."""
        from core.models import SiteSettings
        site = SiteSettings.load()
        site.enable_guardian_portal = True      # optional extension, off by default
        site.save()
        response = self.client.post(reverse('register'), {
            'full_name': 'Test Guardian', 'email': 'guardian@example.com',
            'username': 'testguardian', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-5', 'account_role': 'guardian',
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username='testguardian')
        self.assertEqual(user.profile.role, 'guardian')
        self.assertFalse(hasattr(user, 'student_profile'))

    def test_register_as_staff_requires_explicit_choice(self):
        """Staff is now its own explicit radio option, not an implicit
        fallback when nothing else was picked."""
        response = self.client.post(reverse('register'), {
            'full_name': 'Test Staff', 'email': 'staffperson@example.com',
            'username': 'teststaffperson', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-6', 'account_role': 'staff',
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username='teststaffperson')
        self.assertEqual(user.profile.role, 'staff')

    def test_unrecognized_account_role_falls_back_to_student_not_staff(self):
        """A missing/tampered account_role value should default to the
        safest, most common case (student) rather than silently granting
        a staff account."""
        response = self.client.post(reverse('register'), {
            'full_name': 'Weird Role', 'email': 'weirdrole@example.com',
            'username': 'weirdroleuser', 'password1': 'StrongPass123!', 'password2': 'StrongPass123!',
            'cnic': '12345-1234567-7', 'account_role': 'superadmin', 'program': self.program.pk,
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username='weirdroleuser')
        self.assertEqual(user.profile.role, 'student')


class RoleBasedAccessTests(TestCase):
    """Confirms the RBAC boundaries this project depends on: a student
    can't reach admin/teacher-only pages, and vice versa."""

    def setUp(self):
        self.admin = User.objects.create_user(username='admin1', password='p', is_staff=True, is_superuser=True)
        self.student = User.objects.create_user(username='student1', password='p')
        self.teacher = User.objects.create_user(username='teacher1', password='p')
        self.teacher.profile.role = 'faculty'
        self.teacher.profile.save()

    def test_student_cannot_reach_admin_dashboard(self):
        self.client.force_login(self.student)
        response = self.client.get('/dashboard/admin/')
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_reach_hostel_management(self):
        self.client.force_login(self.student)
        response = self.client.get('/hostel/manage/')
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_reach_hostel_management(self):
        """Hostel/fees/admissions management is admin-only, not teacher-accessible."""
        self.client.force_login(self.teacher)
        response = self.client.get('/hostel/manage/')
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_reach_site_settings(self):
        self.client.force_login(self.teacher)
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_reach_admin_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get('/dashboard/admin/')
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)


class OperationalEndpointTests(TestCase):
    def test_health_endpoint_is_public_and_minimal(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'service': 'ums'})

    def test_readiness_endpoint_reports_database(self):
        response = self.client.get(reverse('readiness'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ready', 'service': 'ums'})


class StudentDashboardAttendanceScopingTests(TestCase):
    """Attendance shown on the student dashboard must be scoped to the
    student's CURRENT semester's registered sections - previously it
    blended every AttendanceRecord ever created for the student across
    every past semester and course (and even generic non-course
    check-ins with no section at all) into one meaningless percentage."""

    def setUp(self):
        from datetime import date, timedelta
        from academics.models import Faculty, Department, Program, Course, CourseSection, CourseRegistration, AcademicSession, Semester
        from attendance.models import AttendanceRecord

        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        today = date.today()
        old_session = AcademicSession.objects.create(year='2024', start_date=today - timedelta(days=400), end_date=today - timedelta(days=250))
        self.old_semester = Semester.objects.create(name='Old Semester', session=old_session, start_date=today - timedelta(days=400), end_date=today - timedelta(days=250))
        current_session = AcademicSession.objects.create(year='2026', start_date=today - timedelta(days=30), end_date=today + timedelta(days=120))
        self.current_semester = Semester.objects.create(name='Current Semester', session=current_session, start_date=today - timedelta(days=30), end_date=today + timedelta(days=120))

        old_course = Course.objects.create(name='Old Course', code='OLD101', program=program, credits=3)
        current_course = Course.objects.create(name='Current Course', code='CUR101', program=program, credits=3)
        self.old_section = CourseSection.objects.create(course=old_course, code='OLD101-A')
        self.current_section = CourseSection.objects.create(course=current_course, code='CUR101-A')

        user = User.objects.create_user(username='attendstudent', password='p')
        self.student = user.student_profile if hasattr(user, 'student_profile') else None
        from registration.models import Student
        self.student = Student.objects.create(user=user, full_name='Attend Student', admission_no='AT-001', program=program)
        CourseRegistration.objects.create(student=self.student, section=self.old_section, status='registered', semester=self.old_semester)
        CourseRegistration.objects.create(student=self.student, section=self.current_section, status='registered', semester=self.current_semester)

        # Old semester: present for 1 of 1 (would be 100% if wrongly included).
        AttendanceRecord.objects.create(student=self.student, section=self.old_section, date=today - timedelta(days=300), present=True)
        # Current semester: present for 1 of 2 (50%).
        AttendanceRecord.objects.create(student=self.student, section=self.current_section, date=today - timedelta(days=5), present=True)
        AttendanceRecord.objects.create(student=self.student, section=self.current_section, date=today - timedelta(days=3), present=False)
        # Generic check-in with no section at all - must not count toward any course.
        AttendanceRecord.objects.create(student=self.student, section=None, date=today - timedelta(days=2), present=True)

        self.AttendanceRecord = AttendanceRecord

    def test_overall_percentage_only_counts_current_semester(self):
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('student-dashboard'))
        self.assertEqual(response.context['attendance_pct'], 50.0)

    def test_per_course_breakdown_only_shows_current_semester_courses(self):
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('student-dashboard'))
        codes = {row['course'].code for row in response.context['attendance_by_course']}
        self.assertIn('CUR101', codes)
        self.assertNotIn('OLD101', codes)
