from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Program, Department, Faculty
from registration.models import Student
from . import services


class DigitalIdTokenTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Engineering & CS")
        dept = Department.objects.create(name="Computer Science", faculty=faculty)
        program = Program.objects.create(name="BSCS", code="BSCS", department=dept)
        user = User.objects.create_user("idcard_student", password="pw")
        self.student = Student.objects.create(
            user=user, full_name="Test Student", admission_no="BSCS-TEST-001",
            program=program, status="active",
        )

    def test_issue_and_verify_round_trip(self):
        token = services.issue_token(self.student)
        self.assertEqual(services.verify_token(token), self.student.pk)

    def test_tampered_token_fails(self):
        token = services.issue_token(self.student)
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        self.assertIsNone(services.verify_token(tampered))

    def test_verify_view_shows_verified_for_valid_token(self):
        token = services.issue_token(self.student)
        resp = self.client.get(reverse("digital-id-verify", args=[token]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ID Verified")
        self.assertContains(resp, self.student.full_name)

    def test_verify_view_shows_not_verified_for_bad_token(self):
        resp = self.client.get(reverse("digital-id-verify", args=["not-a-real-token"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Not Verified")

    def test_verify_reflects_live_status_change(self):
        """The token only carries the student's pk - if status changes
        after the card was printed, verification reflects the current
        status, not whatever was true when the QR was generated."""
        token = services.issue_token(self.student)
        self.student.status = "suspended"
        self.student.save()
        resp = self.client.get(reverse("digital-id-verify", args=[token]))
        self.assertContains(resp, "ID Verified")
        self.assertContains(resp, "not currently active")

    def test_id_card_page_embeds_verify_link(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse("my-id-card"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "/id/verify/")
