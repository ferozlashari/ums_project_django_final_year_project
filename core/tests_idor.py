"""Object-level authorization (IDOR) matrix: changing an id in the URL must never
cross a section, student or office boundary - for every role."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicSession, CourseRegistration, CourseSection, Semester
from assignments.models import Assignment, Submission
from attendance.models import AttendanceSession
from core.models import Profile
from exams.models import GradeEntry
from governance.tests import Base
from hr.models import Staff
from onlineclass.models import OnlineClass
from quizzes.models import Quiz
from registration.models import Student

DENIED = {403, 404}


class IdorBase(Base):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        self.sem = Semester.objects.create(name='Fall', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=60))
        # Teacher B owns section B, with student 2
        self.teacher_b = User.objects.create_user('teachb', password='pw')
        Profile.objects.update_or_create(user=self.teacher_b, defaults={'role': 'faculty'})
        self.staff_b = Staff.objects.create(user=self.teacher_b, employee_id='T2', department=self.dept, role='lecturer', hire_date=today)
        self.section_b = CourseSection.objects.create(course=self.course, code='B', capacity=30, instructor=self.staff_b)
        self.student2 = Student.objects.create(user=User.objects.create_user('stud2', password='pw'), full_name='Stu Two', admission_no='S2', program=self.program)
        # Teacher A (self.teacher) owns section A with student 1
        self.reg1 = CourseRegistration.objects.create(student=self.student, section=self.section, semester=self.sem, status='registered')
        self.reg2 = CourseRegistration.objects.create(student=self.student2, section=self.section_b, semester=self.sem, status='registered')
        self.grade_a = GradeEntry.objects.create(student=self.student, exam=self.exam, registration=self.reg1, marks=Decimal('50'), entered_by=self.teacher)
        self.assign_a = Assignment.objects.create(section=self.section, title='HW', due_date=timezone.now() + datetime.timedelta(days=3), created_by=self.teacher)
        self.sub_a = Submission.objects.create(assignment=self.assign_a, student=self.student, text_answer='x')
        self.quiz_a = Quiz.objects.create(section=self.section, title='Q', created_by=self.teacher)
        self.class_a = OnlineClass.objects.create(title='Live', section=self.section, host=self.staff_rec, scheduled_at=timezone.now())
        self.att_a = AttendanceSession.objects.create(section=self.section, semester=self.sem, date=today, created_by=self.teacher)

    def status(self, user, name, *args, method='get', data=None):
        self.client.force_login(user)
        url = reverse(name, args=args)
        r = self.client.post(url, data or {}) if method == 'post' else self.client.get(url)
        return r.status_code


class TeacherCannotCrossSectionTests(IdorBase):
    """Teacher B pokes at Teacher A's section."""
    def test_marks_page_of_another_teachers_section(self):
        self.assertIn(self.status(self.teacher_b, 'teacher-marks', self.section.pk), DENIED)

    def test_grade_edit_and_unlock_and_correction_on_another_teachers_entry(self):
        self.assertIn(self.status(self.teacher_b, 'grade-edit', self.grade_a.pk), DENIED)
        self.assertIn(self.status(self.teacher_b, 'grade-unlock', self.grade_a.pk, method='post'), DENIED)
        self.assertIn(self.status(self.teacher_b, 'grade-correction-request', self.grade_a.pk), DENIED)

    def test_assignment_submissions_and_grading_of_another_teachers_section(self):
        self.assertIn(self.status(self.teacher_b, 'assignment-submissions', self.assign_a.pk), DENIED)
        self.assertIn(self.status(self.teacher_b, 'grade-submission', self.sub_a.pk, method='post', data={'marks_obtained': '9'}), DENIED)
        self.sub_a.refresh_from_db()
        self.assertIsNone(self.sub_a.marks_obtained)

    def test_quiz_management_of_another_teachers_section(self):
        self.assertIn(self.status(self.teacher_b, 'quiz-questions', self.quiz_a.pk), DENIED)
        self.assertIn(self.status(self.teacher_b, 'quiz-publish', self.quiz_a.pk, method='post'), DENIED)
        self.quiz_a.refresh_from_db()
        self.assertFalse(self.quiz_a.is_published)

    def test_ending_another_teachers_online_class(self):
        self.assertIn(self.status(self.teacher_b, 'class-end', self.class_a.pk, method='post'), DENIED)
        self.class_a.refresh_from_db()
        self.assertNotEqual(self.class_a.status, 'ended')

    def test_attendance_correction_for_another_teachers_session(self):
        self.assertIn(self.status(self.teacher_b, 'attendance-correction-request', self.att_a.pk, method='post'), DENIED)

    def test_other_teachers_student_records_are_closed(self):
        for name in ('marksheet', 'exam-slip', 'gpa-calculator-for', 'id-card'):
            arg = self.student.pk
            self.assertIn(self.status(self.teacher_b, name, arg), DENIED, name)

    def test_teacher_cannot_edit_or_delete_students_or_academic_structure(self):
        self.assertIn(self.status(self.teacher, 'student-edit', self.student.pk), DENIED)
        self.assertIn(self.status(self.teacher, 'student-delete', self.student.pk, method='post'), DENIED)
        self.assertIn(self.status(self.teacher, 'section-edit', self.section_b.pk), DENIED)
        self.assertIn(self.status(self.teacher, 'course-edit', self.course.pk), DENIED)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())


class StudentCannotCrossStudentTests(IdorBase):
    def test_student_cannot_open_another_students_documents(self):
        for name in ('marksheet', 'exam-slip', 'gpa-calculator-for', 'id-card'):
            self.assertIn(self.status(self.student2.user, name, self.student.pk), DENIED, name)

    def test_student_cannot_use_staff_functions(self):
        for name, args in (('grade-edit', (self.grade_a.pk,)), ('teacher-marks', (self.section.pk,)),
                           ('assignment-submissions', (self.assign_a.pk,)), ('quiz-publish', (self.quiz_a.pk,))):
            self.assertIn(self.status(self.student.user, name, *args), DENIED, name)

    def test_student_cannot_drop_someone_elses_registration(self):
        self.assertIn(self.status(self.student2.user, 'drop-registration', self.reg1.pk, method='post'), DENIED)
        self.reg1.refresh_from_db()
        self.assertEqual(self.reg1.status, 'registered')


class OfficeCannotCrossOfficeTests(IdorBase):
    def _holder(self, username, role_code):
        from governance.models import Role, RoleAssignment
        u = User.objects.create_user(username, password='pw')
        Profile.objects.update_or_create(user=u, defaults={'role': 'staff'})
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code=role_code))
        return u

    def test_finance_officer_cannot_touch_academic_records(self):
        fo = self._holder('fo9', 'finance_officer')
        for name, args in (('grade-edit', (self.grade_a.pk,)), ('student-edit', (self.student.pk,)),
                           ('course-edit', (self.course.pk,)), ('section-edit', (self.section.pk,))):
            self.assertIn(self.status(fo, name, *args), DENIED, name)

    def test_it_admin_cannot_edit_marks_or_students(self):
        it = self._holder('it9', 'it_administrator')
        for name, args in (('grade-edit', (self.grade_a.pk,)), ('student-edit', (self.student.pk,)),
                           ('grade-unlock', (self.grade_a.pk,))):
            self.assertIn(self.status(it, name, *args, method=('post' if name == 'grade-unlock' else 'get')), DENIED, name)

    def test_admission_officer_cannot_edit_results(self):
        ao = self._holder('ao9', 'admission_officer')
        self.assertIn(self.status(ao, 'grade-edit', self.grade_a.pk), DENIED)
