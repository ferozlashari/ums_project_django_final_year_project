"""Seat allocation under real concurrency. Needs a database with row locks
(PostgreSQL); on SQLite these tests are skipped rather than pretending to pass."""
import datetime
import threading
import unittest

from django.contrib.auth.models import User
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from academics.models import (
    AcademicSession, Course, CourseRegistration, CourseSection, Curriculum, CurriculumCourse,
    CurriculumSemester, Department, Faculty, Program, Semester,
)
from core.services.academic import AcademicEligibilityService as Svc
from registration.models import Student


def _world(capacity):
    today = timezone.localdate()
    dept = Department.objects.create(name='CS', faculty=Faculty.objects.create(name='Eng'))
    program = Program.objects.create(name='BSCS', code='BSCS', department=dept, duration_years=4)
    sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
    sem = Semester.objects.create(name='Fall', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90))
    course = Course.objects.create(code='CS101', name='Prog', credits=3, program=program)
    cur = Curriculum.objects.create(program=program, name='BSCS', version='2026', total_credits=3)
    cs = CurriculumSemester.objects.create(curriculum=cur, semester_number=1)
    CurriculumCourse.objects.create(curriculum_semester=cs, course=course)
    section = CourseSection.objects.create(course=course, code='A', capacity=capacity)
    students = [Student.objects.create(user=User.objects.create_user(f'u{i}', password='pw'), full_name=f'S{i}',
                                       admission_no=f'A{i}', program=program, status='active', admission_semester=sem)
                for i in range(8)]
    return sem, section, students


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs PostgreSQL row locking')
class ConcurrentRegistrationTests(TransactionTestCase):
    def test_eight_students_racing_for_two_seats_get_exactly_two(self):
        sem, section, students = _world(capacity=2)
        outcomes, barrier = [], threading.Barrier(len(students))

        def work(student):
            try:
                barrier.wait()
                Svc.register_course(student, section.pk, sem)
                outcomes.append('ok')
            except ValueError:
                outcomes.append('full')
            except Exception as exc:                       # anything else is a bug the test must show
                outcomes.append(f'error:{type(exc).__name__}')
            finally:
                close_old_connections()

        threads = [threading.Thread(target=work, args=(s,)) for s in students]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(outcomes.count('ok'), 2, outcomes)
        self.assertEqual(outcomes.count('full'), 6, outcomes)
        self.assertEqual(CourseRegistration.objects.filter(section=section, semester=sem, status='registered').count(), 2)

    def test_same_student_cannot_register_twice_even_in_parallel(self):
        sem, section, students = _world(capacity=5)
        student, results = students[0], []
        barrier = threading.Barrier(2)

        def work():
            try:
                barrier.wait()
                Svc.register_course(student, section.pk, sem)
                results.append('ok')
            except (ValueError, IntegrityError):
                results.append('refused')
            except Exception as exc:
                results.append(f'error:{type(exc).__name__}')
            finally:
                close_old_connections()

        threads = [threading.Thread(target=work) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count('ok'), 1, results)
        self.assertEqual(CourseRegistration.objects.filter(student=student, section=section, semester=sem, status='registered').count(), 1)
