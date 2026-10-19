"""Tests for exams: the marks-entry automatic lock, component-mark
summing, and retake/improvement grade-entry gating.
Run with: python manage.py test exams
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course, Semester, AcademicSession
from core.models import Profile, SiteSettings
from exams.forms import GradeEntryForm
from exams.models import ExamSession, GradeEntry, RetakeApplication
from registration.models import Student


class MarksLockTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        course = Course.objects.create(code='CS101', name='Intro to Programming', credits=3, program=program)
        self.exam = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
        student_user = User.objects.create_user(username='marksstudent', password='p')
        self.student = Student.objects.create(user=student_user, full_name='Marks Student', admission_no='UMS-M-001', program=program)

        teacher_user = User.objects.create_user(username='marksteacher', password='p')
        Profile.objects.update_or_create(user=teacher_user, defaults={'role': 'faculty'})
        from hr.models import Staff
        from academics.models import CourseSection
        staff = Staff.objects.create(user=teacher_user, employee_id='FAC-T-001', department=dept, role='lecturer', hire_date=timezone.localdate())
        section = CourseSection.objects.create(course=course, code='A', capacity=30, instructor=staff)
        # The student sits in this teacher's section - the only reason the teacher may touch their marks.
        import datetime
        from academics.models import AcademicSession, CourseRegistration, Semester
        today = timezone.localdate()
        sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        sem = Semester.objects.create(name='Fall', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=60))
        CourseRegistration.objects.create(student=self.student, section=section, semester=sem, status='registered')
        self.teacher = teacher_user
        admin_user = User.objects.create_user(username='marksadmin', password='p', is_staff=True, is_superuser=True)
        self.admin = admin_user

    def test_component_marks_combine_using_course_weights(self):
        """Course.exam.course defaults to attendance=10/assignment=20/
        midterm=30/final=40 (sums to 100). Each component is entered as
        RAW MARKS out of its own weight-as-max (not a percentage), so
        they add up directly to a 0-100 total."""
        entry = GradeEntry.objects.create(
            student=self.student, exam=self.exam,
            attendance_marks=8, assignment_marks=15, midterm_marks=21, final_marks=36,
        )
        # 8 + 15 + 21 + 36 = 80 out of 100 (max_marks=100) = 80.0
        self.assertEqual(entry.marks, 80.0)

    def test_different_course_weights_change_the_total(self):
        """The whole point of configurable weights: the same component
        scores produce a different final mark under a different scheme."""
        self.exam.course.attendance_weight = 0
        self.exam.course.assignment_weight = 0
        self.exam.course.midterm_weight = 0
        self.exam.course.final_weight = 100
        self.exam.course.save()
        entry = GradeEntry.objects.create(
            student=self.student, exam=self.exam,
            attendance_marks=80, assignment_marks=75, midterm_marks=70, final_marks=90,
        )
        # Only the final exam counts now - 90% of 100 = 90.
        self.assertEqual(entry.marks, 90.0)

    def test_course_weights_must_sum_to_100(self):
        from django.core.exceptions import ValidationError
        self.exam.course.final_weight = 999
        with self.assertRaises(ValidationError):
            self.exam.course.full_clean()

    def test_marks_field_stands_alone_without_components(self):
        """Backward compatible: no components entered means marks is used as-is."""
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=77)
        self.assertEqual(entry.marks, 77)

    def test_entry_not_locked_before_configured_days(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70)
        self.assertFalse(entry.is_locked)

    def test_entry_locks_after_configured_days(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=61))
        entry.refresh_from_db()
        self.assertTrue(entry.is_locked)

    def test_admin_unlock_overrides_lock(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=61))
        entry.refresh_from_db()
        self.assertTrue(entry.is_locked)
        entry.admin_unlocked = True
        entry.save()
        self.assertFalse(entry.is_locked)

    def test_locked_entry_rejects_teacher_edit(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70, entered_by=self.teacher)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=61))
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('grade-edit', args=[entry.pk]), {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': 99, 'attempt_type': 'regular',
        })
        entry.refresh_from_db()
        self.assertEqual(entry.marks, 70)  # unchanged
        self.assertEqual(response.status_code, 302)  # redirected away with an error message

    def test_admin_can_edit_locked_entry(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70, entered_by=self.teacher)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=61))
        self.client.force_login(self.admin)
        self.client.post(reverse('grade-edit', args=[entry.pk]), {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': 99, 'attempt_type': 'regular',
        })
        entry.refresh_from_db()
        self.assertEqual(entry.marks, 99)

    def test_admin_unlock_view(self):
        """Unlocking is the Controller of Examinations' call; the system admin needs an emergency window."""
        from governance.models import EmergencyAccess, Role, RoleAssignment
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=61))
        self.client.force_login(self.admin)                       # no emergency window -> refused
        self.assertEqual(self.client.post(reverse('grade-unlock', args=[entry.pk])).status_code, 403)
        entry.refresh_from_db()
        self.assertFalse(entry.admin_unlocked)
        ctrl = User.objects.create_user('ctrl_unlock', password='p')
        RoleAssignment.objects.create(user=ctrl, role=Role.objects.get(code='exam_controller'))
        self.client.force_login(ctrl)
        self.client.post(reverse('grade-unlock', args=[entry.pk]))
        entry.refresh_from_db()
        self.assertFalse(entry.is_locked)
        self.assertTrue(entry.admin_unlocked)

    def test_configurable_lock_window(self):
        settings = SiteSettings.load()
        settings.marks_lock_days = 5
        settings.save()
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=70)
        GradeEntry.objects.filter(pk=entry.pk).update(entered_at=timezone.now() - timedelta(days=6))
        entry.refresh_from_db()
        self.assertTrue(entry.is_locked)


class RetakeGradeEntryGatingTests(TestCase):
    """A retake/improvement grade can only be recorded once the student has
    an approved application with a paid challan for that exact course -
    otherwise a teacher could record a free re-attempt nobody applied for."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        course = Course.objects.create(code='CS101', name='Intro to Programming', credits=3, program=program)
        self.exam = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
        student_user = User.objects.create_user(username='retakestudent', password='p')
        self.student = Student.objects.create(user=student_user, full_name='Retake Student', admission_no='UMS-R-001', program=program)
        self.original_grade = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=30)  # F

        admin_user = User.objects.create_user(username='retakeadmin', password='p', is_staff=True, is_superuser=True)
        self.admin = admin_user

    def test_retake_grade_rejected_without_approved_application(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('grade-add'), {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': 75, 'attempt_type': 'retake',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GradeEntry.objects.filter(student=self.student, attempt_type='retake').exists())

    def test_retake_grade_accepted_with_approved_and_paid_application(self):
        application = RetakeApplication.objects.create(
            student=self.student, grade_entry=self.original_grade, application_type='retake', status='approved',
        )
        from finance.models import Invoice
        invoice = Invoice.objects.create(
            student=self.student, category='exam_retake', amount=5000,
            reference=f'Retake - {self.exam.course.code}', paid=True,
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse('grade-add'), {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': 75, 'attempt_type': 'retake',
        })
        self.assertTrue(GradeEntry.objects.filter(student=self.student, attempt_type='retake', marks=75).exists())


class ComponentMarksDecimalCalculationTests(TestCase):
    """Regression test for a real bug: GradeEntry.save() crashed with
    `TypeError: unsupported operand type(s) for *: 'decimal.Decimal' and
    'float'` any time component marks (attendance/assignment/midterm/final)
    were entered - which is the normal path from the grading UI, not an
    edge case. The bug was invisible to the rest of the test suite because
    every other grade-entry test only exercised the single-figure `marks`
    path, which never reached the weighted-component calculation at all.
    """

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        semester = Semester.objects.create(name='Fall 2026', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        self.exam = ExamSession.objects.create(name='Midterm', course=self.course, semester=semester, date=timezone.now().date(), max_marks=100)
        user = User.objects.create_user('cmtest_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Component Test', admission_no='CMT-001', program=program, status='active')
        admin_user = User.objects.create_user('cmtest_admin', password='pw', is_staff=True, is_superuser=True)
        Profile.objects.update_or_create(user=admin_user, defaults={'role': 'admin'})
        self.admin = admin_user

    def test_entering_component_marks_does_not_raise_and_computes_correctly(self):
        """The exact repro: default course weights are 10/20/30/40, so
        100% in every component must compute to the full max_marks (100),
        not crash."""
        entry = GradeEntry(
            student=self.student, exam=self.exam,
            attendance_marks=100, assignment_marks=100, midterm_marks=100, final_marks=100,
        )
        entry.save()  # must not raise TypeError
        self.assertEqual(entry.marks, 100)

    def test_partial_component_marks_compute_correct_weighted_value(self):
        # Raw marks within each component's cap (10/20/30/40 by default):
        # attendance=8/10 + assignment=14/20 + midterm=18/30 + final=36/40
        # = 8+14+18+36 = 76 out of 100, scaled to max_marks=100 -> 76.00
        entry = GradeEntry(
            student=self.student, exam=self.exam,
            attendance_marks=8, assignment_marks=14, midterm_marks=18, final_marks=36,
        )
        entry.save()
        self.assertEqual(entry.marks, 76)

    def test_grade_add_view_with_component_marks_succeeds(self):
        """The real HTTP path a teacher actually uses - this is what
        originally crashed with a 500 (surfaced as a generic 'something
        went wrong' page to the teacher)."""
        self.client.force_login(self.admin)
        response = self.client.post(reverse('grade-add'), {
            'student': self.student.pk, 'exam': self.exam.pk,
            'attendance_marks': 9, 'assignment_marks': 17, 'midterm_marks': 25, 'final_marks': 35,
            'attempt_type': 'regular',
        })
        self.assertEqual(response.status_code, 302)  # redirect on success, not a 500
        entry = GradeEntry.objects.get(student=self.student, exam=self.exam)
        self.assertGreater(entry.marks, 0)

    def test_grade_add_view_rejects_completely_empty_submission(self):
        """Neither components nor a single-figure `marks` value - this
        should be a clean validation error, not a crash and not a silent
        zero-marks record."""
        self.client.force_login(self.admin)
        response = self.client.post(reverse('grade-add'), {
            'student': self.student.pk, 'exam': self.exam.pk, 'attempt_type': 'regular',
        })
        self.assertFalse(GradeEntry.objects.filter(student=self.student, exam=self.exam).exists())


class GradeEntryAdminLockAndAuditTests(TestCase):
    """Django admin was a second, unaudited, lock-bypassing path to change
    marks alongside the real grade_edit view - this closes that gap."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        semester = Semester.objects.create(name='Fall 2026', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        self.exam = ExamSession.objects.create(name='Midterm', course=self.course, semester=semester, date=timezone.now().date(), max_marks=100)
        user = User.objects.create_user('adminlocktest_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Admin Lock Test', admission_no='ALT-001', program=program, status='active')
        self.admin = User.objects.create_superuser('adminlocktest_admin', 'a@a.com', 'pw')

    def test_admin_cannot_silently_edit_a_locked_entry(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=50)
        entry.entered_at = timezone.now() - timedelta(days=100)  # force past the lock window
        entry.save(update_fields=['entered_at'])
        self.assertTrue(GradeEntry.objects.get(pk=entry.pk).is_locked)

        self.client.force_login(self.admin)
        resp = self.client.post(f'/admin/exams/gradeentry/{entry.pk}/change/', {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': '99', 'grade': '',
            'attempt_type': 'regular', 'admin_unlocked': '',  # NOT ticked
        })
        entry.refresh_from_db()
        self.assertEqual(entry.marks, 50)  # unchanged - the edit was refused

    def test_admin_can_override_with_admin_unlocked_and_it_gets_audited(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=50)
        entry.entered_at = timezone.now() - timedelta(days=100)
        entry.save(update_fields=['entered_at'])

        self.client.force_login(self.admin)
        self.client.post(f'/admin/exams/gradeentry/{entry.pk}/change/', {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': '99', 'grade': '',
            'attempt_type': 'regular', 'admin_unlocked': 'on',
        })
        entry.refresh_from_db()
        self.assertEqual(entry.marks, 99)

        from core.models import AuditLog
        log = AuditLog.objects.filter(action='GRADE_UPDATED').order_by('-created_at').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.changes['marks'][0], '50.00')
        self.assertEqual(float(log.changes['marks'][1]), 99.0)

    def test_admin_creating_a_new_entry_is_audited(self):
        self.client.force_login(self.admin)
        self.client.post('/admin/exams/gradeentry/add/', {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': '75', 'grade': '',
            'attempt_type': 'regular',
        })
        self.assertTrue(GradeEntry.objects.filter(student=self.student, exam=self.exam, marks=75).exists())
        from core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='GRADE_CREATED').exists())


class GradeIntegrityBugTests(TestCase):
    """Regression tests for a real, serious bug reported with a screenshot:
    a GradeEntry with final_marks=1000 (way outside the valid 0-100
    percentage range) produced marks=412.00 (over max_marks=100) and
    displayed Grade "A" - because (1) component fields had no upper bound
    and (2) the `grade` field was independently teacher-editable free text
    that the results page preferred over the correctly computed
    letter_grade, so a stray/wrong typed grade silently overrode reality.
    """

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        semester = Semester.objects.create(name='Fall 2026', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        self.exam = ExamSession.objects.create(name='Midterm', course=self.course, semester=semester, date=timezone.now().date(), max_marks=100)
        user = User.objects.create_user('gradebug_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Grade Bug Test', admission_no='GBT-001', program=program, status='active')
        self.admin = User.objects.create_superuser('gradebug_admin', 'a@a.com', 'pw')

    def test_out_of_range_component_is_rejected_by_the_form(self):
        """The exact repro: final_marks=1000 must never be accepted."""
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('grade-add'), {
            'student': self.student.pk, 'exam': self.exam.pk,
            'attendance_marks': 10, 'assignment_marks': 10, 'midterm_marks': 30, 'final_marks': 1000,
            'attempt_type': 'regular',
        })
        self.assertFalse(GradeEntry.objects.filter(student=self.student, exam=self.exam).exists())

    def test_marks_can_never_exceed_max_marks_even_via_raw_save(self):
        """Defense in depth: even bypassing form validation entirely (a
        script, a bad migration, direct ORM use), save() itself must clamp
        marks into a sane range rather than trust the caller."""
        entry = GradeEntry(student=self.student, exam=self.exam, marks=999999)
        entry.save()
        self.assertEqual(entry.marks, 100)  # clamped to max_marks
        self.assertEqual(entry.letter_grade, 'A+')  # 100% is a correct A+ on the default scale

    def test_grade_field_is_not_independently_editable(self):
        """`grade` must not appear as a fillable field on the form - it is
        always derived from marks, never separately typed."""
        form = GradeEntryForm()
        self.assertNotIn('grade', form.fields)

    def test_stored_grade_always_matches_computed_percentage(self):
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=29)
        self.assertEqual(entry.grade, 'F')  # 29% is a fail, never "A"
        self.assertEqual(entry.grade, entry.letter_grade)

    def test_results_page_never_shows_a_manually_typed_grade(self):
        """Even a record saved before this fix (grade='A' hand-typed
        against a 29% score) must display correctly once re-rendered,
        since the template now always uses the live-computed letter_grade
        rather than trusting whatever string is stored in `grade`."""
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=29)
        GradeEntry.objects.filter(pk=entry.pk).update(grade='A')  # simulate stale bad data, bypassing save()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('results'))
        self.assertContains(resp, '29.00')
        self.assertNotContains(resp, '<td>A</td>')


class RetakeApplyPageWasUnreachableTests(TestCase):
    """Regression test for a real bug: /exams/retake/apply/<id>/ returned
    405 on GET, even though the view's own docstring and body fully
    implement a GET confirmation page - a stray @require_POST decorator
    was blocking it before the code ever ran, making "Retake &
    Improvement" completely unusable from the UI (every click landed on
    an error, since the link is a plain <a> tag, not a form)."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        semester = Semester.objects.create(name='Fall 2026', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        exam = ExamSession.objects.create(name='Midterm', course=course, semester=semester, date=timezone.now().date(), max_marks=100)
        user = User.objects.create_user('retakebug_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Retake Bug Test', admission_no='RBT-001', program=program, status='active')
        self.entry = GradeEntry.objects.create(student=self.student, exam=exam, marks=40)  # F - eligible for retake

    def test_get_shows_confirmation_page_instead_of_405(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('apply-retake', args=[self.entry.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'CS101')

    def test_post_still_submits_the_application(self):
        self.client.force_login(self.student.user)
        resp = self.client.post(reverse('apply-retake', args=[self.entry.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(RetakeApplication.objects.filter(student=self.student, grade_entry=self.entry).exists())


class GPADisplayZeroValueBugTests(TestCase):
    """Regression test for a real reported bug: a student whose every
    grade is F (genuinely 0.0 GPA/CGPA - a real, meaningful result, not
    missing data) saw "—" instead of "0.00", because the templates used
    Django's `default` filter, which treats 0/0.0 as "empty" and
    substitutes the placeholder - the exact same footgun that would hide
    a real 0% attendance or a real Rs. 0 balance. `default_if_none` only
    substitutes for an actual None, which is what was needed here."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        semester = Semester.objects.create(name='Fall 2026', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        exam = ExamSession.objects.create(name='Midterm', course=course, semester=semester, date=timezone.now().date(), max_marks=100)
        user = User.objects.create_user('gpazero_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='GPA Zero Test', admission_no='GZT-001', program=program, status='active')
        GradeEntry.objects.create(student=self.student, exam=exam, marks=20)  # F -> grade_point 0.0

    def test_all_f_student_shows_real_zero_not_a_dash(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('result-checker'), {'admission_no': self.student.admission_no})
        self.assertEqual(resp.context['cgpa'], 0.0)
        content = resp.content.decode()
        self.assertIn('0.0', content)
        # The dash must not appear where the CGPA number itself is rendered.
        import re
        cgpa_block = re.search(r'CGPA</div><div[^>]*>([^<]*)</div>', content)
        self.assertIsNotNone(cgpa_block)
        self.assertNotIn('—', cgpa_block.group(1))
