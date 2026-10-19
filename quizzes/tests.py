"""Tests for quiz visibility: same registered-section scoping fix as
assignments (see assignments/tests.py for the full reasoning).
Run with: python manage.py test quizzes
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Faculty, Department, Program, Course, CourseSection, CourseRegistration
from quizzes.models import Quiz
from registration.models import Student


class QuizVisibilityTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)

        course1 = Course.objects.create(name='Programming Fundamentals', code='CS101', program=program, credits=3)
        course2 = Course.objects.create(name='Advanced Algorithms', code='CS401', program=program, credits=3)
        self.registered_section = CourseSection.objects.create(course=course1, code='CS101-A')
        self.unregistered_section = CourseSection.objects.create(course=course2, code='CS401-A')

        user = User.objects.create_user(username='quizstudent', password='p')
        self.student = Student.objects.create(user=user, full_name='Quiz Student', admission_no='QS-001', program=program)
        CourseRegistration.objects.create(student=self.student, section=self.registered_section, status='registered')

        self.quiz_registered = Quiz.objects.create(section=self.registered_section, title='Registered Quiz', is_published=True)
        self.quiz_unregistered = Quiz.objects.create(section=self.unregistered_section, title='Unregistered Quiz', is_published=True)

    def test_student_sees_only_registered_section_quizzes(self):
        self.client.force_login(self.student.user)
        response = self.client.get(reverse('quiz-list'))
        titles = [row['quiz'].title for row in response.context['rows']]
        self.assertIn('Registered Quiz', titles)
        self.assertNotIn('Unregistered Quiz', titles)
