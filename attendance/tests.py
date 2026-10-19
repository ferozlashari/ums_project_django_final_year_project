from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

import datetime
from academics.models import Faculty, Department, Program, Course, CourseSection, CourseRegistration, AcademicSession, Semester
from hr.models import Staff
from core.models import Profile
from registration.models import Student
from .models import AttendanceRecord


class BulkAttendanceTests(TestCase):
    """A teacher marking a whole section at once, instead of one student
    per click - the concrete 'mark all students at one time' feature."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)

        teacher_user = User.objects.create_user('bulkatt_teacher', password='pw', first_name='Teacher', last_name='One')
        Profile.objects.filter(user=teacher_user).update(role='faculty')
        self.staff = Staff.objects.create(user=teacher_user, employee_id='EMP-BULK-1', department=dept)
        self.section = CourseSection.objects.create(course=course, code='A', instructor=self.staff, capacity=40)

        today = timezone.localdate()
        session = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        self.semester = Semester.objects.create(name='Fall 2026', session=session, semester_number=1,
                                                start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90))
        self.students = []
        for i in range(3):
            u = User.objects.create_user(f'bulkatt_stu{i}', password='pw')
            s = Student.objects.create(user=u, full_name=f'Student {i}', admission_no=f'BLK-00{i}', program=program, status='active')
            CourseRegistration.objects.create(student=s, section=self.section, semester=self.semester, status='registered')
            self.students.append(s)

        self.teacher_user = teacher_user
        self.today = timezone.localdate().isoformat()

    def test_roster_loads_automatically_for_the_selected_section(self):
        self.client.force_login(self.teacher_user)
        resp = self.client.get(reverse('bulk-attendance'), {'section': self.section.pk, 'date': self.today})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['roster']), 3)

    def test_saving_marks_present_and_absent_correctly_in_one_submit(self):
        self.client.force_login(self.teacher_user)
        # Only student 0 and 2 checked present; student 1 left unchecked (absent).
        self.client.post(reverse('bulk-attendance'), {
            'section': self.section.pk, 'date': self.today,
            f'present_{self.students[0].pk}': 'on',
            f'present_{self.students[2].pk}': 'on',
        })
        records = {r.student_id: r.present for r in AttendanceRecord.objects.filter(section=self.section, date=self.today)}
        self.assertEqual(records[self.students[0].pk], True)
        self.assertEqual(records[self.students[1].pk], False)
        self.assertEqual(records[self.students[2].pk], True)

    def test_resubmitting_the_same_day_updates_instead_of_duplicating(self):
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('bulk-attendance'), {
            'section': self.section.pk, 'date': self.today,
            f'present_{self.students[0].pk}': 'on',
        })
        self.client.post(reverse('bulk-attendance'), {
            'section': self.section.pk, 'date': self.today,
            # student 0 now marked absent on resubmission
        })
        self.assertEqual(AttendanceRecord.objects.filter(section=self.section, date=self.today).count(), 3)
        rec = AttendanceRecord.objects.get(section=self.section, date=self.today, student=self.students[0])
        self.assertFalse(rec.present)

    def test_teacher_cannot_take_attendance_for_a_section_they_do_not_teach(self):
        other_teacher = User.objects.create_user('bulkatt_other', password='pw')
        Profile.objects.filter(user=other_teacher).update(role='faculty')
        self.client.force_login(other_teacher)
        resp = self.client.get(reverse('bulk-attendance'), {'section': self.section.pk, 'date': self.today}, follow=True)
        self.assertEqual(len(resp.context.get('roster', [])), 0)

    def test_student_cannot_access_bulk_attendance(self):
        self.client.force_login(self.students[0].user)
        resp = self.client.get(reverse('bulk-attendance'))
        self.assertEqual(resp.status_code, 403)


    def test_no_active_semester_gives_a_clear_message_not_a_crash(self):
        Semester.objects.all().delete()
        self.client.force_login(self.teacher_user)
        resp = self.client.post(reverse('bulk-attendance'), {'section': self.section.pk, 'date': self.today}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No active semester')
        self.assertEqual(AttendanceRecord.objects.count(), 0)
