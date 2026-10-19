"""Tests for OnlineClass status: it must reflect real elapsed time, not
just the stored `status` field which only changes when a teacher
explicitly clicks End (a class could otherwise show "Scheduled" and sit
in Upcoming forever after it actually finished).
Run with: python manage.py test onlineclass
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course, CourseSection
from core.models import Profile
from hr.models import Staff
from onlineclass.models import OnlineClass
from registration.models import Student


class OnlineClassStatusTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        course = Course.objects.create(name='Programming Fundamentals', code='CS101', program=program, credits=3)
        self.section = CourseSection.objects.create(course=course, code='CS101-A')

        staff_user = User.objects.create_user(username='teacher1', password='p')
        Profile.objects.update_or_create(user=staff_user, defaults={'role': 'faculty'})
        self.staff = Staff.objects.create(user=staff_user, employee_id='EMP-1', department=dept, role='lecturer')

    def _make_class(self, minutes_from_now, duration_mins=60, status='scheduled'):
        return OnlineClass.objects.create(
            title='Test Class', section=self.section, host=self.staff,
            scheduled_at=timezone.now() + timedelta(minutes=minutes_from_now),
            duration_mins=duration_mins, status=status,
        )

    def test_future_class_displays_as_scheduled(self):
        oc = self._make_class(minutes_from_now=60)
        self.assertEqual(oc.display_status, 'scheduled')

    def test_class_within_its_window_displays_as_live(self):
        oc = self._make_class(minutes_from_now=-10, duration_mins=60)  # started 10 min ago, runs 60 min
        self.assertEqual(oc.display_status, 'live')

    def test_class_past_its_window_displays_as_ended_even_if_never_clicked_end(self):
        """The exact bug from the report: a class scheduled well in the
        past with a normal duration must show as ended, not linger as
        'Scheduled' forever just because nobody clicked the End button."""
        oc = self._make_class(minutes_from_now=-120, duration_mins=60)  # started 2h ago, 60 min long -> long over
        self.assertEqual(oc.display_status, 'ended')

    def test_explicitly_ended_class_stays_ended_even_if_technically_still_in_window(self):
        oc = self._make_class(minutes_from_now=-10, duration_mins=60, status='ended')
        self.assertEqual(oc.display_status, 'ended')

    def test_upcoming_list_excludes_classes_whose_window_has_passed(self):
        live = self._make_class(minutes_from_now=-5, duration_mins=30)
        long_over = self._make_class(minutes_from_now=-120, duration_mins=60)
        future = self._make_class(minutes_from_now=60)

        self.client.force_login(self.staff.user)
        response = self.client.get(reverse('class-list'))
        upcoming_ids = {c.pk for c in response.context['upcoming']}
        past_ids = {c.pk for c in response.context['past']}

        self.assertIn(live.pk, upcoming_ids)
        self.assertIn(future.pk, upcoming_ids)
        self.assertNotIn(long_over.pk, upcoming_ids)
        self.assertIn(long_over.pk, past_ids)


class OnlineClassVisibilityTests(TestCase):
    """A student should only see online classes for sections they're
    actually registered in, not every section of every course in their
    program (same fix/reasoning as assignments/tests.py)."""

    def setUp(self):
        from academics.models import CourseRegistration

        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        course1 = Course.objects.create(name='Programming Fundamentals', code='CS101', program=program, credits=3)
        course2 = Course.objects.create(name='Advanced Algorithms', code='CS401', program=program, credits=3)
        self.registered_section = CourseSection.objects.create(course=course1, code='CS101-A')
        self.unregistered_section = CourseSection.objects.create(course=course2, code='CS401-A')

        staff_user = User.objects.create_user(username='vteacher', password='p')
        self.staff = Staff.objects.create(user=staff_user, employee_id='EMP-V', department=dept, role='lecturer')

        student_user = User.objects.create_user(username='onlinestudent', password='p')
        self.student = Student.objects.create(user=student_user, full_name='Online Student', admission_no='OS-001', program=program)
        CourseRegistration.objects.create(student=self.student, section=self.registered_section, status='registered')

    def test_student_sees_only_registered_section_classes(self):
        registered_class = OnlineClass.objects.create(
            title='Registered Class', section=self.registered_section, host=self.staff,
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        unregistered_class = OnlineClass.objects.create(
            title='Unregistered Class', section=self.unregistered_section, host=self.staff,
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('class-list'))
        titles = {c.title for c in response.context['upcoming']}
        self.assertIn('Registered Class', titles)
        self.assertNotIn('Unregistered Class', titles)
