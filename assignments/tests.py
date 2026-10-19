"""Tests for assignment visibility: a student must only see assignments
for course sections they are actually registered in - previously any
student in a program could see EVERY section's assignments for that
program, including ones they had never registered for.
Run with: python manage.py test assignments
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Faculty, Department, Program, Course, CourseSection, CourseRegistration
from assignments.models import Assignment
from core.models import Profile
from registration.models import Student


class AssignmentVisibilityTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        course1 = Course.objects.create(name='Programming Fundamentals', code='CS101', program=self.program, credits=3)
        course2 = Course.objects.create(name='Advanced Algorithms', code='CS401', program=self.program, credits=3)
        self.registered_section = CourseSection.objects.create(course=course1, code='CS101-A')
        self.unregistered_section = CourseSection.objects.create(course=course2, code='CS401-A')

        user = User.objects.create_user(username='assignstudent', password='p')
        self.student = Student.objects.create(user=user, full_name='Assign Student', admission_no='AS-001', program=self.program)
        CourseRegistration.objects.create(student=self.student, section=self.registered_section, status='registered')
        # Deliberately NOT registered in self.unregistered_section, even
        # though it belongs to the same program.

        self.assignment_registered = Assignment.objects.create(
            section=self.registered_section, title='Registered Section Assignment',
            due_date=timezone.now() + timedelta(days=7),
        )
        self.assignment_unregistered = Assignment.objects.create(
            section=self.unregistered_section, title='Unregistered Section Assignment',
            due_date=timezone.now() + timedelta(days=7),
        )

    def test_student_sees_only_registered_section_assignments(self):
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('assignment-list'))
        titles = [row['assignment'].title for row in response.context['rows']]
        self.assertIn('Registered Section Assignment', titles)
        self.assertNotIn('Unregistered Section Assignment', titles)

    def test_dropped_registration_also_hides_assignment(self):
        """Same program, same section, but the registration status is
        'dropped' - should behave the same as never having registered."""
        reg = CourseRegistration.objects.get(student=self.student, section=self.registered_section)
        reg.status = 'dropped'
        reg.save()
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('assignment-list'))
        titles = [row['assignment'].title for row in response.context['rows']]
        self.assertNotIn('Registered Section Assignment', titles)
