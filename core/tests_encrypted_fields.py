from django.test import TestCase

from core.encrypted_fields import DECRYPTION_UNAVAILABLE, is_decryption_unavailable
from core.security import get_fernet
from academics.models import Faculty, Department, Program
from registration.models import Student
from registration.forms import StudentForm
from django.contrib.auth.models import User


class EncryptedFieldDecryptFailureTests(TestCase):
    """A field encrypted with a key that no longer matches
    FIELD_ENCRYPTION_KEY must never surface raw ciphertext to a template
    or a form - it should come back as a clearly-marked placeholder, and
    that placeholder must never be re-saved as if it were real data."""

    def setUp(self):
        faculty = Faculty.objects.create(name="Engineering & CS")
        dept = Department.objects.create(name="Computer Science", faculty=faculty)
        self.program = Program.objects.create(name="BSCS", code="BSCS", department=dept)
        user = User.objects.create_user("cnic_test", password="pw")
        self.student = Student.objects.create(
            user=user, full_name="CNIC Test", admission_no="BSCS-CNIC-1",
            program=self.program, status="active", cnic="12345-1234567-1",
        )

    def test_valid_cnic_round_trips_normally(self):
        self.student.refresh_from_db()
        self.assertEqual(self.student.cnic, "12345-1234567-1")

    def test_corrupted_ciphertext_returns_safe_placeholder_not_raw_bytes(self):
        # Simulate "encrypted with a different/old key" by writing bytes
        # that look like Fernet ciphertext but won't decrypt with the
        # current key - exactly the FIELD_ENCRYPTION_KEY-mismatch scenario.
        from django.db import connection
        fake_ciphertext = "gAAAAABnotarealtoken_but_looks_like_one_1234567890"
        with connection.cursor() as cur:
            cur.execute(
                f"UPDATE {Student._meta.db_table} SET cnic = %s WHERE id = %s",
                [fake_ciphertext, self.student.id],
            )
        reloaded = Student.objects.get(pk=self.student.pk)
        self.assertTrue(is_decryption_unavailable(reloaded.cnic))
        self.assertEqual(str(reloaded.cnic), "Protected information unavailable")
        # Never the raw ciphertext:
        self.assertNotEqual(reloaded.cnic, fake_ciphertext)

    def test_form_rejects_resaving_the_placeholder_as_real_cnic(self):
        from django.db import connection
        fake_ciphertext = "gAAAAABnotarealtoken_but_looks_like_one_1234567890"
        with connection.cursor() as cur:
            cur.execute(
                f"UPDATE {Student._meta.db_table} SET cnic = %s WHERE id = %s",
                [fake_ciphertext, self.student.id],
            )
        reloaded = Student.objects.get(pk=self.student.pk)
        form = StudentForm(instance=reloaded, data={
            "full_name": reloaded.full_name,
            "admission_no": reloaded.admission_no,
            "status": "active",
            "cnic": str(DECRYPTION_UNAVAILABLE),  # user submitted the form unchanged
        })
        form.is_valid()
        self.assertIn("cnic", form.errors)
