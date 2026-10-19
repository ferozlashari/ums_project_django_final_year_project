"""Tests for the authoritative Enrollment record: history on program
change, one active row per student, and curriculum pinning."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from academics.models import Curriculum, Department, Faculty, Program
from registration.models import Enrollment, Student


class EnrollmentBackboneTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        self.bscs = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.bsse = Program.objects.create(name='BSSE', code='BSSE', department=dept)
        self.cur_v1 = Curriculum.objects.create(program=self.bscs, name='BSCS', version='2025', is_active=True)

    def student(self, name, program=None):
        u = User.objects.create_user(name, password='pw')
        return Student.objects.create(user=u, full_name=name, admission_no=f'A-{name}', program=program)

    def test_assigning_a_program_creates_one_active_enrollment(self):
        s = self.student('e1', self.bscs)
        active = Enrollment.objects.filter(student=s, status='active')
        self.assertEqual(active.count(), 1)
        self.assertEqual(active.first().program, self.bscs)
        self.assertEqual(s.current_enrollment.program, self.bscs)

    def test_curriculum_is_pinned_at_enrollment_time(self):
        s = self.student('e2', self.bscs)
        self.assertEqual(s.current_enrollment.curriculum, self.cur_v1)
        # A newer curriculum version replaces "active" later...
        cur_v2 = Curriculum.objects.create(program=self.bscs, name='BSCS', version='2026', is_active=True)
        self.cur_v1.is_active = False
        self.cur_v1.save()
        s.refresh_from_db()
        # ...but the already-enrolled student's pinned curriculum does not move.
        self.assertEqual(s.current_enrollment.curriculum, self.cur_v1)
        from core.services.academic import AcademicEligibilityService
        self.assertEqual(AcademicEligibilityService.active_curriculum(s), self.cur_v1)

    def test_changing_program_closes_the_old_enrollment_and_opens_a_new_one(self):
        s = self.student('e3', self.bscs)
        first = s.current_enrollment
        s.program = self.bsse
        s.save()
        first.refresh_from_db()
        self.assertEqual(first.status, 'transferred')
        self.assertIsNotNone(first.ended_on)
        self.assertEqual(s.current_enrollment.program, self.bsse)
        self.assertEqual(Enrollment.objects.filter(student=s, status='active').count(), 1)
        self.assertEqual(Enrollment.objects.filter(student=s).count(), 2)   # full history kept

    def test_no_program_means_no_enrollment_row(self):
        s = self.student('e4', None)
        self.assertEqual(Enrollment.objects.filter(student=s).count(), 0)
        self.assertIsNone(s.current_enrollment)

    def test_saving_without_changing_program_does_not_duplicate_enrollment(self):
        s = self.student('e5', self.bscs)
        s.phone = '0300-0000000'
        s.save()
        self.assertEqual(Enrollment.objects.filter(student=s).count(), 1)

    def test_admission_enrolls_with_a_real_enrollment_record(self):
        from admissions.models import Application, EntryTest
        from admissions.services import AdmissionService
        applicant = User.objects.create_user('applicant1', password='pw')
        app = Application.objects.create(applicant=applicant, program=self.bscs, admission_type='open_merit', full_name='Applicant One')
        EntryTest.objects.create(application=app, roll_number='R1', test_date=datetime.date.today(), marks_obtained=80)
        AdmissionService.enroll(app)
        student = Student.objects.get(user=applicant)
        self.assertEqual(student.current_enrollment.program, self.bscs)


class PositionUsesPinnedCurriculumTests(TestCase):
    """Regression test: academic_position() must resolve curriculum through
    active_curriculum() (the pinned one), not re-derive it independently -
    otherwise position and recommendations could silently disagree."""

    def test_position_stays_on_the_pinned_curriculum_after_a_new_version_is_activated(self):
        import datetime
        from academics.models import (AcademicSession, Course, CurriculumCourse, CurriculumSemester, Department,
                                      Faculty, Program, Semester)
        from core.services.academic import AcademicEligibilityService as Svc

        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        old_cur = Curriculum.objects.create(program=program, name='BSCS', version='2025', is_active=True)
        old_sem1 = CurriculumSemester.objects.create(curriculum=old_cur, semester_number=1)
        c1 = Course.objects.create(code='OLD101', name='Old Course', credits=3, program=program)
        CurriculumCourse.objects.create(curriculum_semester=old_sem1, course=c1)

        u = User.objects.create_user('pin1', password='pw')
        s = Student.objects.create(user=u, full_name='Pin One', admission_no='PIN-1', program=program)
        self.assertEqual(Svc.academic_position(s)['total_semesters'], 1)  # matches old curriculum's 1 semester

        new_cur = Curriculum.objects.create(program=program, name='BSCS', version='2026', is_active=True)
        CurriculumSemester.objects.create(curriculum=new_cur, semester_number=1)
        CurriculumSemester.objects.create(curriculum=new_cur, semester_number=2)
        old_cur.is_active = False
        old_cur.save()

        s.refresh_from_db()
        position = Svc.academic_position(s)
        self.assertEqual(position['total_semesters'], 1)      # still pinned to the OLD curriculum

        # A student who enrolls AFTER the switch gets the new one.
        u2 = User.objects.create_user('pin2', password='pw')
        s2 = Student.objects.create(user=u2, full_name='Pin Two', admission_no='PIN-2', program=program)
        self.assertEqual(Svc.academic_position(s2)['total_semesters'], 2)
