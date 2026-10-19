"""Tests for core: the audit log actually records sensitive actions and
cannot be edited/deleted through the admin.
Run with: python manage.py test core
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course
from core.models import AuditLog, log_action
from exams.models import ExamSession, GradeEntry
from registration.models import Student


class AuditLogTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        course = Course.objects.create(code='CS101', name='Intro to Programming', credits=3, program=program)
        self.exam = ExamSession.objects.create(name='Final', course=course, date=timezone.localdate(), max_marks=100)
        student_user = User.objects.create_user(username='auditstudent', password='p')
        self.student = Student.objects.create(user=student_user, full_name='Audit Student', admission_no='UMS-A-001', program=program)
        self.admin = User.objects.create_user(username='auditadmin', password='p', is_staff=True, is_superuser=True)

    def test_log_action_creates_entry(self):
        log_action(self.admin, 'TEST_ACTION', obj='some record', changes={'x': ['1', '2']})
        entry = AuditLog.objects.get(action='TEST_ACTION')
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.changes, {'x': ['1', '2']})

    def test_log_action_never_raises_on_unserializable_changes(self):
        # A caller could accidentally pass a Decimal, date, model instance,
        # or arbitrary object inside `changes` instead of stringifying it
        # first. log_action must neither raise NOR silently drop the whole
        # audit entry in that case - it normalizes the value via
        # _json_safe() so the record still gets written.
        import datetime
        from decimal import Decimal
        log_action(self.admin, 'TEST_ACTION_SAFE', obj=object(), changes={
            'amount': Decimal('123.45'),
            'when': datetime.date(2026, 1, 1),
            'student': self.student,
            'weird': object(),
        })
        entry = AuditLog.objects.get(action='TEST_ACTION_SAFE')
        self.assertEqual(entry.changes['amount'], '123.45')
        self.assertEqual(entry.changes['when'], '2026-01-01')
        self.assertIn('Audit Student', entry.changes['student'])
        self.assertIsInstance(entry.changes['weird'], str)

    def test_grade_edit_writes_audit_entry(self):
        from hr.models import Staff
        from academics.models import CourseSection
        staff = Staff.objects.create(user=self.admin, employee_id='FAC-A-001', hire_date=timezone.localdate())
        CourseSection.objects.create(course=self.exam.course, code='A', capacity=30, instructor=staff)
        entry = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=50)
        self.client.force_login(self.admin)
        self.client.post(reverse('grade-edit', args=[entry.pk]), {
            'student': self.student.pk, 'exam': self.exam.pk, 'marks': 90, 'attempt_type': 'regular',
        })
        self.assertTrue(AuditLog.objects.filter(action='GRADE_UPDATED').exists())
        log = AuditLog.objects.get(action='GRADE_UPDATED')
        self.assertEqual(log.changes['marks'], ['50.00', '90'])

    def test_audit_log_admin_is_read_only(self):
        from django.contrib import admin as django_admin
        model_admin = django_admin.site._registry[AuditLog]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))

    def test_audit_log_page_requires_admin(self):
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('audit-log'))
        self.assertEqual(response.status_code, 403)

    def test_audit_log_page_accessible_to_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('audit-log'))
        self.assertEqual(response.status_code, 200)
