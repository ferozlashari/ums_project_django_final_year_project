from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course, Semester, AcademicSession
from exams.models import ExamSession
from registration.models import Student
from .models import ExamAttendance


class WebAuthnIdentityVerificationTests(TestCase):
    """The only identity-verification path left in this app now that
    physical biometric hardware support has been removed: a student's
    own passkey (WebAuthn), verified entirely on their device."""

    def setUp(self):
        faculty = Faculty.objects.create(name="Engineering & CS")
        dept = Department.objects.create(name="Computer Science", faculty=faculty)
        program = Program.objects.create(name="BSCS", code="BSCS", department=dept)
        course = Course.objects.create(code="CS101", name="Programming Fundamentals", credits=3, program=program)
        session = AcademicSession.objects.create(year="2026-2027", start_date=timezone.now().date(), end_date=timezone.now().date() + timezone.timedelta(days=300))
        semester = Semester.objects.create(name="Fall 2026", session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timezone.timedelta(days=150))
        self.exam = ExamSession.objects.create(name="Midterm", course=course, semester=semester, date=timezone.now().date(), max_marks=100)

        user = User.objects.create_user("webauthn_bio_stu", password="pw")
        self.student = Student.objects.create(
            user=user, full_name="WebAuthn Student", admission_no="BSCS-WA-1", program=program, status="active",
        )

    def test_verify_exam_attendance_requires_recent_webauthn_check(self):
        self.client.force_login(self.student.user)
        self.client.post(reverse("verify-exam-attendance", args=[self.exam.pk]))
        self.assertFalse(ExamAttendance.objects.filter(exam=self.exam, student=self.student).exists())

    def test_verify_exam_attendance_succeeds_after_webauthn_check(self):
        self.client.force_login(self.student.user)
        session = self.client.session
        session["webauthn_verified_until"] = (timezone.now() + timezone.timedelta(seconds=60)).isoformat()
        session.save()
        self.client.post(reverse("verify-exam-attendance", args=[self.exam.pk]))
        self.assertTrue(ExamAttendance.objects.filter(exam=self.exam, student=self.student, method="webauthn").exists())

    def test_non_student_cannot_verify_exam_attendance(self):
        admin = User.objects.create_user("webauthn_bio_admin", password="pw", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.post(reverse("verify-exam-attendance", args=[self.exam.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_physical_device_urls_no_longer_exist(self):
        """Locks in the removal - these named routes must be gone, not
        just unlinked from navigation. "biometric-command-center" is
        deliberately NOT in this list: it now exists as a real, tested page
        (see biometrics/tests_command_center.py) - real devices, real
        last_seen_at-derived status, real today's event counts, and the
        exact "No biometric devices configured." empty state the spec
        requires. This guard remains for names that are still unimplemented."""
        from django.urls import NoReverseMatch
        for name in ("biometric-device-list", "biometric-enrollment-list", "biometric-punch-log"):
            with self.assertRaises(NoReverseMatch):
                reverse(name)
