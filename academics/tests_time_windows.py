"""Time-period rules: course selection window, drop deadline, exam
registration window, and attendance date validation."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import (AcademicSession, Course, CourseRegistration, CourseSection, Curriculum,
                              CurriculumCourse, CurriculumSemester, Department, Faculty, Program, Semester)
from core.models import Profile, SiteSettings
from core.services.academic import AcademicEligibilityService as Svc
from exams.models import ExamSession, GradeEntry
from hr.models import Staff
from registration.models import Student

H = datetime.timedelta


class WindowBase(TestCase):
    def setUp(self):
        today = timezone.localdate()
        faculty = Faculty.objects.create(name='Faculty')
        self.dept = Department.objects.create(name='CS', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=self.dept)
        session = AcademicSession.objects.create(year='2026-2027', start_date=today - H(days=60), end_date=today + H(days=300))
        self.sem = Semester.objects.create(name='Fall 2026', session=session, semester_number=1,
                                           start_date=today - H(days=30), end_date=today + H(days=90))
        self.course = Course.objects.create(code='CS101', name='Programming', credits=3, program=self.program)
        cur = Curriculum.objects.create(program=self.program, name='BSCS', version='2026', total_credits=12)
        cs1 = CurriculumSemester.objects.create(curriculum=cur, semester_number=1)
        CurriculumCourse.objects.create(curriculum_semester=cs1, course=self.course)
        self.section = CourseSection.objects.create(course=self.course, code='A', capacity=30)
        u = User.objects.create_user('win_stu', password='pw')
        self.student = Student.objects.create(user=u, full_name='Win Student', admission_no='W-1', program=self.program,
                                              status='active', admission_semester=self.sem)

    def register(self):
        return CourseRegistration.objects.create(student=self.student, section=self.section, semester=self.sem, status='registered')


class RegistrationWindowTests(WindowBase):
    def test_not_open_yet_blocks_registration_with_the_open_date(self):
        self.sem.registration_open = timezone.now() + H(days=2)
        self.sem.save()
        res = Svc.registration_eligibility(self.student, self.section, self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('has not opened yet' in r and 'opens on' in r for r in res.reasons))

    def test_after_close_blocks_registration_with_the_close_date(self):
        self.sem.registration_close = timezone.now() - H(hours=1)
        self.sem.save()
        res = Svc.registration_eligibility(self.student, self.section, self.sem)
        self.assertFalse(res.eligible)
        self.assertTrue(any('deadline has passed' in r and 'closed on' in r for r in res.reasons))

    def test_inside_the_window_is_allowed(self):
        self.sem.registration_open = timezone.now() - H(days=1)
        self.sem.registration_close = timezone.now() + H(days=5)
        self.sem.save()
        self.assertTrue(Svc.registration_eligibility(self.student, self.section, self.sem).eligible)

    def test_automatic_assignment_also_respects_a_closed_window(self):
        self.sem.registration_close = timezone.now() - H(hours=1)
        self.sem.save()
        Svc.auto_assign_all_students(self.sem)
        self.assertFalse(CourseRegistration.objects.exists())


class DropDeadlineTests(WindowBase):
    def drop(self, reg):
        self.client.force_login(self.student.user)
        return self.client.post(reverse('drop-registration', args=[reg.pk]), follow=True)

    def test_explicit_drop_deadline_in_the_future_allows_drop(self):
        self.sem.drop_deadline = timezone.now() + H(days=3)
        self.sem.save()
        reg = self.register()
        self.drop(reg)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'dropped')

    def test_drop_after_the_deadline_is_refused_with_the_date(self):
        self.sem.drop_deadline = timezone.now() - H(hours=2)
        self.sem.save()
        reg = self.register()
        resp = self.drop(reg)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'registered')
        self.assertContains(resp, 'drop deadline')
        self.assertContains(resp, 'can no longer be dropped')

    def test_without_a_drop_deadline_it_follows_the_registration_close(self):
        self.sem.registration_close = timezone.now() - H(days=1)
        self.sem.save()
        self.assertEqual(self.sem.drop_state(), 'closed')
        reg = self.register()
        self.drop(reg)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'registered')

    def test_with_no_dates_at_all_the_site_default_drop_window_applies(self):
        # Semester started 30 days ago; default window is 14 days -> closed.
        self.assertEqual(self.sem.drop_state(), 'closed')
        cfg = SiteSettings.load()
        cfg.default_drop_window_days = 60          # now 60 days after start -> still open
        cfg.save()
        self.assertEqual(self.sem.drop_state(), 'open')
        reg = self.register()
        self.drop(reg)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'dropped')

    def test_a_course_with_a_recorded_result_cannot_be_dropped(self):
        self.sem.drop_deadline = timezone.now() + H(days=3)
        self.sem.save()
        reg = self.register()
        exam = ExamSession.objects.create(name='CS101 Mid', course=self.course, semester=self.sem, date=self.sem.start_date)
        GradeEntry.objects.create(student=self.student, exam=exam, marks=70)
        resp = self.drop(reg)
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'registered')
        self.assertContains(resp, 'recorded result')

    def test_cannot_drop_someone_elses_registration(self):
        self.sem.drop_deadline = timezone.now() + H(days=3)
        self.sem.save()
        reg = self.register()
        other = User.objects.create_user('other_win', password='pw')
        self.client.force_login(other)
        resp = self.client.post(reverse('drop-registration', args=[reg.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_my_registrations_page_shows_drop_closed_after_deadline(self):
        self.sem.drop_deadline = timezone.now() - H(hours=1)
        self.sem.save()
        self.register()
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('my-registrations'))
        self.assertContains(resp, 'Drop closed')
        self.assertNotContains(resp, 'Drop this course?')

    def test_course_selection_page_shows_the_window_banner(self):
        self.sem.registration_close = timezone.now() + H(days=4)
        self.sem.save()
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('browse-sections'))
        self.assertContains(resp, 'Course selection for')
        self.assertContains(resp, 'Drop deadline')


class ExamRegistrationWindowTests(WindowBase):
    def test_states(self):
        self.assertEqual(self.sem.exam_registration_state(), 'not_configured')
        self.sem.exam_registration_open = timezone.now() + H(days=1)
        self.assertEqual(self.sem.exam_registration_state(), 'not_open')
        self.sem.exam_registration_open = timezone.now() - H(days=2)
        self.sem.exam_registration_close = timezone.now() - H(days=1)
        self.assertEqual(self.sem.exam_registration_state(), 'closed')
        self.sem.exam_registration_close = timezone.now() + H(days=1)
        self.assertEqual(self.sem.exam_registration_state(), 'open')

    def test_retake_application_refused_when_exam_registration_is_closed(self):
        exam = ExamSession.objects.create(name='CS101 Final', course=self.course, semester=self.sem, date=self.sem.start_date)
        entry = GradeEntry.objects.create(student=self.student, exam=exam, marks=30)
        self.sem.exam_registration_open = timezone.now() - H(days=10)
        self.sem.exam_registration_close = timezone.now() - H(days=1)
        self.sem.save()
        self.client.force_login(self.student.user)
        resp = self.client.post(reverse('apply-retake', args=[entry.pk]), follow=True)
        from exams.models import RetakeApplication
        self.assertFalse(RetakeApplication.objects.exists())
        self.assertContains(resp, 'Exam registration')


class AttendanceDateTests(WindowBase):
    def setUp(self):
        super().setUp()
        self.teacher_user = User.objects.create_user('win_teacher', password='pw')
        Profile.objects.filter(user=self.teacher_user).update(role='faculty')
        self.teacher = Staff.objects.create(user=self.teacher_user, employee_id='E-W', department=self.dept)
        self.section.instructor = self.teacher
        self.section.save()
        self.register()
        self.client.force_login(self.teacher_user)

    def post(self, day):
        return self.client.post(reverse('bulk-attendance'), {'section': self.section.pk, 'date': day.isoformat(),
                                                             f'present_{self.student.pk}': 'on'}, follow=True)

    def test_future_date_is_refused(self):
        from attendance.models import AttendanceRecord
        resp = self.post(timezone.localdate() + H(days=1))
        self.assertContains(resp, 'future date')
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_date_outside_the_semester_is_refused(self):
        from attendance.models import AttendanceRecord
        resp = self.post(self.sem.start_date - H(days=5))
        self.assertContains(resp, 'outside')
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_valid_past_date_inside_the_semester_is_saved(self):
        from attendance.models import AttendanceRecord
        self.post(timezone.localdate() - H(days=3))
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_malformed_date_does_not_crash(self):
        resp = self.client.get(reverse('bulk-attendance'), {'section': self.section.pk, 'date': 'not-a-date'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not a valid date')
