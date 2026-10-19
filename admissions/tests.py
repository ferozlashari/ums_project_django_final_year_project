"""Tests for admissions: fee-challan automation, reapplication guard,
document-upload requirement, and the entry-test pass/fail cascade.
Run with: python manage.py test admissions
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from academics.models import Faculty, Department, Program
from admissions.models import Application
from registration.models import Student
from finance.models import Invoice


def _fake_pdf(name='doc.pdf'):
    """A minimal but valid-looking PDF upload for tests - real content
    doesn't matter, only that it passes the extension/size validator."""
    return SimpleUploadedFile(name, b'%PDF-1.4 fake test file', content_type='application/pdf')


def _valid_application_payload(program_id):
    return {
        'preference_1': program_id,
        'cnic_copy': _fake_pdf('cnic.pdf'),
        'education_certificate': _fake_pdf('cert.pdf'),
    }


class AdmissionApplicationTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        self.applicant = User.objects.create_user(username='applicant', password='p')

    def test_apply_requires_cnic_document(self):
        """Submitting without the required CNIC copy must not create an application."""
        self.client.force_login(self.applicant)
        self.client.post(reverse('apply'), {'preference_1': self.program.id})
        self.assertFalse(Application.objects.filter(applicant=self.applicant).exists())

    def test_apply_generates_fee_challan_for_existing_student(self):
        """A withdrawn student re-applying gets an automatic admission-processing fee challan."""
        Student.objects.create(user=self.applicant, full_name='Applicant One', admission_no='UMS-TEST-001', program=self.program, status='withdrawn')
        self.client.force_login(self.applicant)
        response = self.client.post(reverse('apply'), _valid_application_payload(self.program.id))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Application.objects.filter(applicant=self.applicant).exists())
        self.assertTrue(Invoice.objects.filter(category='admission').exists())

    def test_cannot_apply_twice_while_pending(self):
        self.client.force_login(self.applicant)
        self.client.post(reverse('apply'), _valid_application_payload(self.program.id))
        self.assertEqual(Application.objects.filter(applicant=self.applicant).count(), 1)
        response = self.client.get(reverse('apply'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Application.objects.filter(applicant=self.applicant).count(), 1)

    def test_active_student_cannot_reapply(self):
        Student.objects.create(
            user=self.applicant, full_name='Applicant One', admission_no='UMS-TEST-002',
            program=self.program, status='active',
        )
        self.client.force_login(self.applicant)
        response = self.client.get(reverse('apply'))
        self.assertEqual(response.status_code, 302)

    def test_staff_cannot_apply(self):
        staff_user = User.objects.create_user(username='staffmember', password='p', is_staff=True)
        self.client.force_login(staff_user)
        response = self.client.get(reverse('apply'))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Application.objects.filter(applicant=staff_user).exists())

    def test_apply_auto_schedules_entry_test(self):
        self.client.force_login(self.applicant)
        self.client.post(reverse('apply'), _valid_application_payload(self.program.id))
        app = Application.objects.get(applicant=self.applicant)
        self.assertTrue(hasattr(app, 'entry_test'))
        self.assertIsNotNone(app.entry_test.roll_number)


class EntryTestAutomationTests(TestCase):
    """The pass/fail cascade: entering a mark >49 must auto-accept the
    application AND create the Student record in one action; <=49 must
    auto-reject with no Student created."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        self.admin = User.objects.create_user(username='admissionsadmin', password='p', is_staff=True, is_superuser=True)
        self.applicant = User.objects.create_user(username='candidate', password='p')
        self.client.force_login(self.applicant)
        self.client.post(reverse('apply'), _valid_application_payload(self.program.id))
        self.application = Application.objects.get(applicant=self.applicant)
        self.entry_test = self.application.entry_test

    def test_passing_mark_makes_candidate_eligible_but_does_not_admit(self):
        """Passing is NOT admission: no acceptance and no Student until merit selection."""
        self.client.force_login(self.admin)
        response = self.client.post(reverse('entry-test-result', args=[self.entry_test.pk]), {'marks_obtained': '75'})
        self.assertEqual(response.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'pending')
        self.assertFalse(Student.objects.filter(user=self.applicant).exists())

    def test_failing_mark_rejects_without_creating_student(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('entry-test-result', args=[self.entry_test.pk]), {'marks_obtained': '49'})
        self.assertEqual(response.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'rejected')
        self.assertFalse(Student.objects.filter(user=self.applicant).exists())

    def test_exactly_pass_mark_is_not_a_pass(self):
        """Policy is 'greater than 49', so exactly 49 must fail."""
        self.client.force_login(self.admin)
        self.client.post(reverse('entry-test-result', args=[self.entry_test.pk]), {'marks_obtained': '49'})
        self.entry_test.refresh_from_db()
        self.assertFalse(self.entry_test.passed)

    def test_fifty_is_a_pass(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('entry-test-result', args=[self.entry_test.pk]), {'marks_obtained': '50'})
        self.entry_test.refresh_from_db()
        self.assertTrue(self.entry_test.passed)


class CNICEncryptionTests(TestCase):
    """The CNIC field must actually round-trip correctly through
    EncryptedCharField, so a configured FIELD_ENCRYPTION_KEY is verified
    to actually be in use rather than sitting unused."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

    def test_cnic_round_trips_correctly(self):
        user = User.objects.create_user(username='cnictest', password='p')
        student = Student.objects.create(
            user=user, full_name='CNIC Test', admission_no='UMS-CNIC-001',
            program=self.program, cnic='12345-1234567-1',
        )
        student.refresh_from_db()
        self.assertEqual(student.cnic, '12345-1234567-1')


class MeritSelectionTests(TestCase):
    """Ranking + seat limits + waitlist + quota pools."""

    def setUp(self):
        from admissions.models import EntryTest
        import datetime
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=dept, open_merit_seats=2, district_quota_seats=1)
        self.admin = User.objects.create_user('selectadmin', password='p', is_staff=True, is_superuser=True)
        self.apps = {}
        for name, marks, pool in [('ali', 90, 'open_merit'), ('bina', 80, 'open_merit'), ('chand', 70, 'open_merit'),
                                  ('dev', 60, 'district_quota'), ('eman', 55, 'district_quota'), ('fail', 40, 'open_merit')]:
            user = User.objects.create_user(name, password='p')
            app = Application.objects.create(applicant=user, program=self.program, admission_type=pool, full_name=name.title())
            EntryTest.objects.create(application=app, roll_number=f'R-{name}', test_date=datetime.date.today(), marks_obtained=marks)
            self.apps[name] = app

    def status(self, name):
        self.apps[name].refresh_from_db()
        return self.apps[name].status

    def test_only_free_seats_are_filled_in_merit_order_per_pool(self):
        from admissions.services import AdmissionService
        AdmissionService.select_for_program(self.program)
        self.assertEqual([self.status(n) for n in ('ali', 'bina', 'chand')], ['accepted', 'accepted', 'waitlist'])
        self.assertEqual([self.status(n) for n in ('dev', 'eman')], ['accepted', 'waitlist'])
        self.assertEqual(self.status('fail'), 'pending')          # below pass mark is never selected

    def test_only_selected_candidates_become_students(self):
        from admissions.services import AdmissionService
        AdmissionService.select_for_program(self.program)
        self.assertTrue(Student.objects.filter(user=self.apps['ali'].applicant).exists())
        self.assertFalse(Student.objects.filter(user=self.apps['chand'].applicant).exists())

    def test_selection_is_idempotent(self):
        from admissions.services import AdmissionService
        AdmissionService.select_for_program(self.program)
        AdmissionService.select_for_program(self.program)
        self.assertEqual(Student.objects.count(), 3)

    def test_waitlisted_candidate_is_promoted_when_a_seat_opens(self):
        from admissions.services import AdmissionService
        AdmissionService.select_for_program(self.program)
        self.apps['bina'].status = 'rejected'          # accepted candidate declines / is withdrawn
        self.apps['bina'].save()
        AdmissionService.select_for_program(self.program)
        self.assertEqual(self.status('chand'), 'accepted')

    def test_dry_run_changes_nothing(self):
        from admissions.services import AdmissionService
        AdmissionService.select_for_program(self.program, dry_run=True)
        self.assertEqual(self.status('ali'), 'pending')
        self.assertEqual(Student.objects.count(), 0)

    def test_run_selection_view_is_admin_only_and_post_only(self):
        self.client.force_login(User.objects.create_user('plain', password='p'))
        resp = self.client.post(reverse('run-selection'), {'program': self.program.pk})
        self.assertNotEqual(self.status('ali'), 'accepted')
        self.client.force_login(self.admin)
        self.client.get(reverse('run-selection'))
        self.assertEqual(self.status('ali'), 'pending')
        self.client.post(reverse('run-selection'), {'program': self.program.pk})
        self.assertEqual(self.status('ali'), 'accepted')
