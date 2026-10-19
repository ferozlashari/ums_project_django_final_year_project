from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class LocalAssistantSmokeTests(TestCase):
    def test_local_assistant_is_safe_without_external_api(self):
        user = User.objects.create_user(username='assistantstudent', password='StrongPass123!')
        from core.models import Profile
        Profile.objects.update_or_create(user=user, defaults={'role': 'student'})
        from ai_assistant.local_assistant import answer
        result = answer(user, 'hello')
        self.assertTrue(result)
        self.assertNotIn('traceback', result.lower())


class AutomationCommandTests(TestCase):
    def test_automation_dry_run_completes(self):
        from django.core.management import call_command
        call_command('run_automation', '--dry-run')


class RegistrationDeadlineReminderTests(TestCase):
    """The 'registration deadline approaching -> reminder' automation
    event: students who haven't registered for a closing semester get
    notified, students who have already registered don't."""

    def setUp(self):
        from academics.models import Faculty, Department, Program, Course, CourseSection, Semester, AcademicSession
        from registration.models import Student
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        session = AcademicSession.objects.create(year='Test', start_date=timezone.localdate(), end_date=timezone.localdate())
        self.semester = Semester.objects.create(
            session=session, name='Closing Semester', semester_number=1,
            start_date=timezone.localdate(), end_date=timezone.localdate(),
            registration_close=timezone.now() + timezone.timedelta(days=2),
        )
        course = Course.objects.create(code='CS101', name='Intro', credits=3, program=self.program)
        self.section = CourseSection.objects.create(course=course, code='A', capacity=30)

        self.unregistered = Student.objects.create(
            user=User.objects.create_user(username='unregistered1', password='p'),
            full_name='Unregistered', admission_no='UMS-U-1', program=self.program, status='active',
        )
        self.registered = Student.objects.create(
            user=User.objects.create_user(username='registered1', password='p'),
            full_name='Registered', admission_no='UMS-R-1', program=self.program, status='active',
        )
        from academics.models import CourseRegistration
        CourseRegistration.objects.create(student=self.registered, section=self.section, semester=self.semester, status='registered')

    def test_unregistered_student_gets_reminder(self):
        from core.services.automation import AutomationService
        from core.models import Notification
        stats = AutomationService.run(dry_run=False)
        self.assertGreaterEqual(stats['registration_deadline'], 1)
        self.assertTrue(Notification.objects.filter(user=self.unregistered.user, title__icontains='deadline').exists())

    def test_registered_student_does_not_get_reminder(self):
        from core.services.automation import AutomationService
        from core.models import Notification
        AutomationService.run(dry_run=False)
        self.assertFalse(Notification.objects.filter(user=self.registered.user, title__icontains='deadline').exists())

    def test_dry_run_counts_but_does_not_notify(self):
        from core.services.automation import AutomationService
        from core.models import Notification
        stats = AutomationService.run(dry_run=True)
        self.assertGreaterEqual(stats['registration_deadline'], 1)
        self.assertFalse(Notification.objects.filter(user=self.unregistered.user).exists())


class AutomationRunLoggingTests(TestCase):
    """The run_automation management command (used by cron/systemd timers)
    should leave the same audit trail a web-triggered run does, so the
    Automation Center's "Last Run" / "Recent Runs" reflect scheduled runs
    too, not only ones clicked through the browser."""

    def test_management_command_logs_audit_entry(self):
        from django.core.management import call_command
        from core.models import AuditLog
        call_command('run_automation', '--dry-run')
        entry = AuditLog.objects.filter(action='AUTOMATION_RUN').order_by('-created_at').first()
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.actor)  # system-triggered, no human actor
        self.assertIn('dry run', entry.object_repr)

    def test_automation_center_shows_last_run_from_command(self):
        from django.core.management import call_command
        from django.contrib.auth.models import User
        call_command('run_automation', '--dry-run')
        admin = User.objects.create_user('automation_admin', password='pw', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse('automation-center'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['last_run'])
        self.assertContains(resp, 'Scheduled')
