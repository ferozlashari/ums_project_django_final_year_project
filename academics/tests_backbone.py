"""Tests for the academic backbone: curriculum-gated registration,
carry-over recommendations, automatic assignment for every student,
per-semester seat counting, fee hold, standing and isolated automation."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from academics.models import (
    AcademicSession, Course, CourseRegistration, CourseSection, Curriculum, CurriculumCourse,
    CurriculumSemester, Department, Faculty, Program, Semester,
)
from core.models import AutomationRun, ExceptionRecord, SiteSettings
from core.services.academic import AcademicEligibilityService as Svc, AcademicProgressService
from core.services.automation import AutomationService
from finance.models import Invoice
from registration.models import Student


class BackboneBase(TestCase):
    def setUp(self):
        today = timezone.localdate()
        faculty = Faculty.objects.create(name='Faculty of Engineering & Computer Science')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='BSCS', department=dept, duration_years=4)
        session = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        self.sem = Semester.objects.create(name='Fall 2026', session=session, semester_number=1,
                                           start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90))
        self.cs101 = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=self.program)
        self.mth101 = Course.objects.create(code='MTH101', name='Calculus', credits=3, program=self.program)
        self.cs102 = Course.objects.create(code='CS102', name='OOP', credits=3, program=self.program)
        self.cs102.prerequisites.add(self.cs101)
        self.cs301 = Course.objects.create(code='CS301', name='Advanced Topics', credits=3, program=self.program)
        self.outside = Course.objects.create(code='XX999', name='Not in curriculum', credits=3, program=self.program)

        cur = Curriculum.objects.create(program=self.program, name='BSCS', version='2026', total_credits=12)
        s1 = CurriculumSemester.objects.create(curriculum=cur, semester_number=1)
        s2 = CurriculumSemester.objects.create(curriculum=cur, semester_number=2)
        s3 = CurriculumSemester.objects.create(curriculum=cur, semester_number=3)
        CurriculumCourse.objects.create(curriculum_semester=s1, course=self.cs101)
        CurriculumCourse.objects.create(curriculum_semester=s1, course=self.mth101)
        CurriculumCourse.objects.create(curriculum_semester=s2, course=self.cs102)
        CurriculumCourse.objects.create(curriculum_semester=s3, course=self.cs301)

        self.sec = {c.code: CourseSection.objects.create(course=c, code='A', capacity=30)
                    for c in (self.cs101, self.mth101, self.cs102, self.cs301, self.outside)}

    def student(self, name, status='active'):
        u = User.objects.create_user(name, password='pw')
        return Student.objects.create(user=u, full_name=name.title(), admission_no=f'ADM-{name}', program=self.program,
                                      status=status, admission_semester=self.sem)


class CurriculumGatingTests(BackboneBase):
    def test_course_outside_active_curriculum_is_blocked(self):
        s = self.student('gate1')
        res = Svc.registration_eligibility(s, self.sec['XX999'], self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('active curriculum' in r for r in res.reasons))

    def test_later_semester_course_is_blocked_for_a_first_semester_student(self):
        s = self.student('gate2')
        res = Svc.registration_eligibility(s, self.sec['CS301'], self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('curriculum semester 3' in r for r in res.reasons))

    def test_current_semester_course_is_allowed(self):
        s = self.student('gate3')
        self.assertTrue(Svc.registration_eligibility(s, self.sec['CS101'], self.sem).eligible)

    def test_prerequisite_still_enforced(self):
        s = self.student('gate4')
        res = Svc.registration_eligibility(s, self.sec['CS102'], self.sem)
        self.assertFalse(res.eligible)

    def test_position_reports_final_semester_flag(self):
        s = self.student('gate5')
        self.assertIn('is_final_semester', Svc.academic_position(s, self.sem))


class SeatsAndFeeHoldTests(BackboneBase):
    def test_last_terms_registrations_do_not_consume_this_terms_seats(self):
        today = timezone.localdate()
        old_session = AcademicSession.objects.create(year='2025-2026', start_date=today - datetime.timedelta(days=400), end_date=today - datetime.timedelta(days=100))
        old_sem = Semester.objects.create(name='Fall 2025', session=old_session, semester_number=1,
                                          start_date=today - datetime.timedelta(days=400), end_date=today - datetime.timedelta(days=200))
        sec = self.sec['CS101']
        sec.capacity = 1
        sec.save()
        other = self.student('seatold')
        CourseRegistration.objects.create(student=other, section=sec, semester=old_sem, status='registered')
        me = self.student('seatnew')
        self.assertTrue(Svc.registration_eligibility(me, sec, self.sem).eligible)
        CourseRegistration.objects.create(student=me, section=sec, semester=self.sem, status='registered')
        third = self.student('seatthird')
        res = Svc.registration_eligibility(third, sec, self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('No seats' in r for r in res.reasons))

    def test_overdue_fee_blocks_registration_only_when_policy_enabled(self):
        s = self.student('fee1')
        Invoice.objects.create(student=s, amount=Decimal('1000'), due_date=timezone.localdate() - datetime.timedelta(days=5))
        self.assertTrue(Svc.registration_eligibility(s, self.sec['CS101'], self.sem).eligible)
        cfg = SiteSettings.load()
        cfg.block_registration_on_overdue_fees = True
        cfg.save()
        res = Svc.registration_eligibility(s, self.sec['CS101'], self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('overdue' in r for r in res.reasons))


class AutoAssignmentTests(BackboneBase):
    def test_recommendations_are_required_courses_with_met_prerequisites(self):
        s = self.student('rec1')
        codes = {i.course.code for i in Svc.recommended_courses(s, self.sem)}
        self.assertEqual(codes, {'CS101', 'MTH101'})   # CS102 needs CS101; CS301 is a later semester

    def test_auto_assign_registers_every_active_student_and_skips_inactive(self):
        a, b = self.student('auto1'), self.student('auto2')
        inactive = self.student('auto3', status='suspended')
        totals = Svc.auto_assign_all_students(self.sem)
        self.assertEqual(totals['errors'], 0)
        for st in (a, b):
            got = set(CourseRegistration.objects.filter(student=st, status='registered', semester=self.sem)
                      .values_list('section__course__code', flat=True))
            self.assertEqual(got, {'CS101', 'MTH101'})
        self.assertFalse(CourseRegistration.objects.filter(student=inactive).exists())

    def test_auto_assign_is_idempotent(self):
        self.student('idem1')
        Svc.auto_assign_all_students(self.sem)
        first = CourseRegistration.objects.count()
        Svc.auto_assign_all_students(self.sem)
        self.assertEqual(CourseRegistration.objects.count(), first)

    def test_dry_run_creates_nothing(self):
        self.student('dry1')
        Svc.auto_assign_all_students(self.sem, dry_run=True)
        self.assertEqual(CourseRegistration.objects.count(), 0)

    def test_one_bad_student_does_not_stop_the_rest_and_is_recorded(self):
        self.student('bad1')
        good = self.student('good1')
        real = Svc.auto_assign_current_courses.__func__

        def flaky(cls, student, semester=None, dry_run=False):
            if student.full_name == 'Bad1':
                raise RuntimeError('boom')
            return real(cls, student, semester, dry_run)
        with mock.patch.object(Svc, 'auto_assign_current_courses', classmethod(flaky)):
            totals = Svc.auto_assign_all_students(self.sem)
        self.assertEqual(totals['errors'], 1)
        self.assertTrue(CourseRegistration.objects.filter(student=good).exists())
        self.assertTrue(ExceptionRecord.objects.filter(code='auto_assign_failed').exists())


class StandingAndAutomationTests(BackboneBase):
    def test_standing_thresholds(self):
        self.assertEqual(AcademicProgressService.standing_for(None), 'No Results Yet')
        self.assertEqual(AcademicProgressService.standing_for(Decimal('1.50')), 'Academic Probation')
        self.assertEqual(AcademicProgressService.standing_for(Decimal('3.00')), 'Good Standing')
        self.assertEqual(AcademicProgressService.standing_for(Decimal('3.80')), 'Honor Roll')

    def test_calculate_without_results_is_safe(self):
        s = self.student('calc1')
        p = AcademicProgressService.calculate(s)
        self.assertIsNone(p['cgpa'])
        self.assertEqual(p['standing'], 'No Results Yet')
        self.assertEqual(p['semester_gpas'], [])

    def test_full_run_records_each_task_and_completes(self):
        self.student('run1')
        AutomationService.run()
        run = AutomationRun.objects.latest('created_at')
        self.assertEqual(run.status, 'completed')
        self.assertEqual(set(run.tasks.values_list('name', flat=True)), set(AutomationService.TASKS))
        self.assertTrue(CourseRegistration.objects.exists())

    def test_a_failing_task_makes_the_run_partial_and_is_recorded(self):
        with mock.patch.object(AutomationService, '_task_course_assignment', side_effect=RuntimeError('db down')):
            AutomationService.run()
        run = AutomationRun.objects.latest('created_at')
        self.assertEqual(run.status, 'partial')
        failed = run.tasks.get(name='course_assignment')
        self.assertEqual(failed.status, 'failed')
        self.assertIn('db down', failed.error)
        self.assertTrue(ExceptionRecord.objects.filter(code='automation_task_failed').exists())
        self.assertEqual(run.tasks.get(name='housekeeping').status, 'completed')
