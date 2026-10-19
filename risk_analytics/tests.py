"""Tests for risk_analytics: the expanded scoring engine actually factors
in failed courses and outstanding fees, not just attendance/grade average.
Run with: python manage.py test risk_analytics
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course
from exams.models import ExamSession, GradeEntry
from finance.models import Invoice
from registration.models import Student
from risk_analytics.models import RiskFlag
from risk_analytics.scoring import recalculate_risk_flags


class RiskScoringTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

    def _make_student(self, username):
        user = User.objects.create_user(username=username, password='p')
        return Student.objects.create(user=user, full_name=username, admission_no=f'UMS-{username}', program=self.program, status='active')

    def test_clean_student_gets_no_flag(self):
        student = self._make_student('clean1')
        recalculate_risk_flags()
        self.assertFalse(RiskFlag.objects.filter(student=student).exists())

    def test_failed_course_raises_risk_level(self):
        student = self._make_student('failer1')
        course = Course.objects.create(code='CS101', name='Intro', credits=3, program=self.program)
        exam = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
        GradeEntry.objects.create(student=student, exam=exam, marks=20)  # F
        recalculate_risk_flags()
        flag = RiskFlag.objects.get(student=student)
        self.assertEqual(flag.failed_courses_count, 1)
        self.assertIn(flag.level, ('medium', 'high'))
        self.assertIn('failing grade', flag.reasons)

    def test_two_failed_courses_is_high_risk(self):
        student = self._make_student('failer2')
        for code in ['CS101', 'CS102']:
            course = Course.objects.create(code=code, name=code, credits=3, program=self.program)
            exam = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
            GradeEntry.objects.create(student=student, exam=exam, marks=20)  # F
        recalculate_risk_flags()
        flag = RiskFlag.objects.get(student=student)
        self.assertEqual(flag.failed_courses_count, 2)
        self.assertEqual(flag.level, 'high')

    def test_outstanding_fee_flags_at_least_medium(self):
        student = self._make_student('debtor1')
        Invoice.objects.create(student=student, category='semester', amount=1000, paid=False)
        recalculate_risk_flags()
        flag = RiskFlag.objects.get(student=student)
        self.assertTrue(flag.has_outstanding_fees)
        self.assertIn(flag.level, ('medium', 'high'))
        self.assertIn('outstanding', flag.reasons.lower())

    def test_paid_invoice_does_not_flag_fees(self):
        student = self._make_student('payer1')
        Invoice.objects.create(student=student, category='semester', amount=1000, paid=True)
        recalculate_risk_flags()
        self.assertFalse(RiskFlag.objects.filter(student=student).exists())

    def test_retake_pass_clears_original_failure(self):
        """A course later passed via retake should not keep counting as a
        failure - only the LATEST attempt per course counts."""
        student = self._make_student('retaker1')
        course = Course.objects.create(code='CS101', name='Intro', credits=3, program=self.program)
        exam1 = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
        GradeEntry.objects.create(student=student, exam=exam1, marks=20, attempt_type='regular')  # F
        import time
        exam2 = ExamSession.objects.create(name='Retake Final', course=course, date=timezone.localdate(), max_marks=100)
        g2 = GradeEntry.objects.create(student=student, exam=exam2, marks=75, attempt_type='retake')  # pass
        # Force the retake to be the later entry chronologically.
        GradeEntry.objects.filter(pk=g2.pk).update(entered_at=timezone.now() + __import__('datetime').timedelta(seconds=10))
        recalculate_risk_flags()
        flag = RiskFlag.objects.filter(student=student).first()
        self.assertTrue(flag is None or flag.failed_courses_count == 0)
