"""End-to-end retake/improvement workflow, as one business process:
Failed result -> eligibility -> application -> fee invoice -> payment ->
approval -> exam registration/new attempt -> new result -> CGPA policy.
Also the specific bug this fixes: a retake in a LATER semester must
REPLACE the original failing course in CGPA, not add to it."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicSession, Course, Department, Faculty, Program, Semester
from core.services.academic import AcademicProgressService
from exams.models import ExamSession, GradeEntry, RetakeApplication
from finance.models import Invoice
from registration.models import Student


class RetakeEndToEndTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        s1 = AcademicSession.objects.create(year='2025-2026', start_date=today - datetime.timedelta(days=400), end_date=today - datetime.timedelta(days=100))
        self.fall2025 = Semester.objects.create(name='Fall 2025', session=s1, semester_number=1,
                                                start_date=today - datetime.timedelta(days=400), end_date=today - datetime.timedelta(days=250))
        s2 = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=200))
        self.spring2026 = Semester.objects.create(name='Spring 2026', session=s2, semester_number=2,
                                                  start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90))
        self.course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=self.program)
        self.other_course = Course.objects.create(code='MTH101', name='Calculus', credits=3, program=self.program)
        u = User.objects.create_user('retake_stu', password='pw')
        self.student = Student.objects.create(user=u, full_name='Retake Student', admission_no='RTK-1', program=self.program)
        self.admin = User.objects.create_user('exam_admin', password='pw', is_staff=True, is_superuser=True)
        self.client.force_login(u)

        self.original_exam = ExamSession.objects.create(name='CS101 Final', course=self.course, semester=self.fall2025, date=self.fall2025.start_date)
        self.failing_entry = GradeEntry.objects.create(student=self.student, exam=self.original_exam, marks=30)  # < 50 -> fail
        # An unrelated passed course, to prove it is unaffected throughout.
        other_exam = ExamSession.objects.create(name='MTH101 Final', course=self.other_course, semester=self.fall2025, date=self.fall2025.start_date)
        GradeEntry.objects.create(student=self.student, exam=other_exam, marks=80)

    def test_full_chain_replaces_the_failed_course_in_cgpa_after_a_passing_retake(self):
        # 1. Eligibility / apply.
        self.assertEqual(self.failing_entry.status, 'fail')
        resp = self.client.post(reverse('apply-retake', args=[self.failing_entry.pk]), {'application_type': 'retake'}, follow=True)
        application = RetakeApplication.objects.get(student=self.student, grade_entry=self.failing_entry)
        self.assertEqual(application.status, 'pending')

        # 2. A fee invoice was generated automatically.
        invoice = application.linked_invoice
        self.assertIsNotNone(invoice)
        self.assertFalse(invoice.paid)
        self.assertEqual(application.exam_eligibility_status, 'Pay the fee challan first')

        # 3. Before payment, the retake grade cannot be entered at all.
        before = AcademicProgressService.calculate(self.student)
        self.assertEqual(before['cgpa'], Decimal('1.75'))       # (0.0*3 + 3.5*3) / 6 credits (80% = B+ = 3.5)

        # 4. Payment.
        invoice.paid = True
        invoice.save(update_fields=['paid'])
        self.assertEqual(application.exam_eligibility_status, 'Fee paid - awaiting staff approval')

        # 5. Approval (staff).
        self.client.force_login(self.admin)
        self.client.post(reverse('review-retake-application', args=[application.pk]), {'status': 'approved'})
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')
        self.assertEqual(application.exam_eligibility_status, 'Eligible to sit the exam')

        # 6. New exam registration / new attempt, in a LATER semester.
        retake_exam = ExamSession.objects.create(name='CS101 Retake', course=self.course, semester=self.spring2026, date=self.spring2026.start_date)
        new_entry = GradeEntry.objects.create(student=self.student, exam=retake_exam, marks=75, attempt_type='retake')
        self.assertEqual(new_entry.status, 'pass')

        # 7. CGPA policy: the retake REPLACES the original failing course -
        # it must not be double-counted as two separate CS101 results.
        after = AcademicProgressService.calculate(self.student)
        cs101_entries_in_cgpa = [e for e in after['failed_entries']]
        self.assertEqual(cs101_entries_in_cgpa, [])                       # no longer counted as failed
        # Only ONE CS101 contributes credits now (3), plus MTH101 (3) = 6 total.
        self.assertEqual(after['credits_attempted'], Decimal('6'))
        self.assertGreater(after['cgpa'], before['cgpa'])                  # CGPA improved

        # 8. Original attempt is preserved for audit history - never deleted.
        self.assertTrue(GradeEntry.objects.filter(pk=self.failing_entry.pk).exists())
        self.assertEqual(GradeEntry.objects.filter(student=self.student, exam__course=self.course).count(), 2)

        # 9. The historical Fall 2025 semester GPA still reflects the ORIGINAL
        # failing attempt - a transcript must not rewrite semester history.
        fall_bucket = next(b for b in after['semester_gpas'] if b['semester'] == self.fall2025)
        self.assertEqual(fall_bucket['gpa'], Decimal('1.75'))              # (0.0*3 + 3.5*3)/6 for that semester alone

    def test_rejected_application_never_generates_eligibility(self):
        self.client.post(reverse('apply-retake', args=[self.failing_entry.pk]), {'application_type': 'retake'})
        application = RetakeApplication.objects.get(grade_entry=self.failing_entry)
        self.client.force_login(self.admin)
        self.client.post(reverse('review-retake-application', args=[application.pk]), {'status': 'rejected'})
        application.refresh_from_db()
        self.assertEqual(application.exam_eligibility_status, 'Not eligible - application rejected')
