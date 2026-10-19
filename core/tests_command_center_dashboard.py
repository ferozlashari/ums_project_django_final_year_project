"""Regression test for the University Command Center admin dashboard: the
new stat fields must be real, live database counts."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Course, CourseSection, Department, Faculty, Program
from registration.models import Student


class CommandCenterDashboardTests(TestCase):
    def test_program_course_section_counts_are_real(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Intro', credits=3, program=program)
        CourseSection.objects.create(course=course, code='A', capacity=30)
        admin = User.objects.create_user('dash_admin', password='pw', is_staff=True, is_superuser=True)
        from core.models import Profile
        Profile.objects.filter(user=admin).update(role='admin')
        self.client.force_login(admin)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.context['stats']['program_count'], 1)
        self.assertEqual(resp.context['stats']['course_count'], 1)
        self.assertEqual(resp.context['stats']['section_count'], 1)
        self.assertContains(resp, 'University Command Center')
