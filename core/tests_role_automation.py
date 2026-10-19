"""Teacher / officer / student automation."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import (AcademicSession, Course, CourseRegistration, CourseSection, Department, Faculty,
                              Program, Semester)
from assignments.models import Assignment
from attendance.models import AttendanceRecord, AttendanceSession
from core.models import AutomationRun, Notification, Profile, SiteSettings
from core.services.role_automation import (ResultWorkflowService, StudentAutomationService,
                                           TeacherAutomationService as T)
from exams.models import AssessmentComponent, AssessmentMark, AssessmentScheme, ResultPublication
from governance.models import Role, RoleAssignment
from hr.models import Staff
from registration.models import Student
from timetable.models import Room, TimeSlot, TimetableAssignment
from core.services.role_automation import DAY_CODES


class Base(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        fac = Faculty.objects.create(name='F')
        self.dept = Department.objects.create(name='CS', faculty=fac)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=self.dept, semester_fee=50000)
        sess = AcademicSession.objects.create(year='2026-2027', start_date=self.today - datetime.timedelta(days=30),
                                              end_date=self.today + datetime.timedelta(days=300))
        self.sem = Semester.objects.create(name='Fall 2026', session=sess, semester_number=1,
                                           start_date=self.today - datetime.timedelta(days=30),
                                           end_date=self.today + datetime.timedelta(days=90))
        self.t1 = self.teacher('t1')
        self.t2 = self.teacher('t2')
        self.sec1 = self.section('CS101', self.t1)       # t1, timetabled today
        self.sec1b = self.section('CS102', self.t1)      # t1, NOT timetabled today
        self.sec2 = self.section('CS201', self.t2)       # t2, timetabled today
        room = Room.objects.create(name='R1', capacity=50)
        slot = TimeSlot.objects.create(day=DAY_CODES[self.today.weekday()], start_time=datetime.time(9), end_time=datetime.time(10))
        for s in (self.sec1, self.sec2):
            TimetableAssignment.objects.create(section=s, room=room, timeslot=slot, semester=self.sem)
        self.alice = self.student('alice'); self.bob = self.student('bob'); self.carl = self.student('carl')
        for st in (self.alice, self.bob):
            self.register(st, self.sec1)
        self.register(self.alice, self.sec1b)
        self.register(self.carl, self.sec2)
        self.root = User.objects.create_superuser('root', 'r@x.com', 'pw')
        from governance.models import EmergencyAccess      # break-glass window: system owner may act while no office holder exists
        EmergencyAccess.objects.create(user=self.root, reason='Test: no office holders configured yet',
                                       expires_at=timezone.now() + datetime.timedelta(minutes=30))

    def user(self, name, role='student'):
        u = User.objects.create_user(name, password='pw')
        Profile.objects.filter(user=u).update(role=role)
        return u

    def teacher(self, name):
        return Staff.objects.create(user=self.user(name, 'faculty'), employee_id=f'E-{name}', department=self.dept)

    def section(self, code, teacher):
        c = Course.objects.create(code=code, name=code, credits=3, program=self.program)
        return CourseSection.objects.create(course=c, code='A', instructor=teacher, capacity=40)

    def student(self, name):
        return Student.objects.create(user=self.user(name), full_name=name.title(), admission_no=f'A-{name}',
                                      program=self.program, status='active')

    def register(self, st, sec):
        return CourseRegistration.objects.create(student=st, section=sec, semester=self.sem, status='registered')

    def scheme(self, course):
        sc = AssessmentScheme.objects.create(course=course)
        mid = AssessmentComponent.objects.create(scheme=sc, name='Midterm', component_type='midterm', weight=30, max_marks=30, order=1)
        fin = AssessmentComponent.objects.create(scheme=sc, name='Final', component_type='final', weight=70, max_marks=70, order=2)
        return sc, mid, fin

    def login(self, user):
        self.client.force_login(user)


class TeacherAttendanceTests(Base):
    url = '/teacher/attendance/today/'

    def test_todays_sheet_lists_only_my_timetabled_classes(self):
        self.login(self.t1.user)
        r = self.client.get(self.url)
        codes = {s['section'].course.code for s in r.context['sheets']}
        self.assertEqual(codes, {'CS101'})            # not CS102 (untimetabled), not CS201 (other teacher)

    def test_show_all_adds_my_untimetabled_sections_but_never_others(self):
        self.login(self.t1.user)
        codes = {s['section'].course.code for s in self.client.get(self.url + '?all=1').context['sheets']}
        self.assertEqual(codes, {'CS101', 'CS102'})

    def test_save_all_records_present_and_absent_in_one_post(self):
        self.login(self.t1.user)
        r = self.client.post(self.url, {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on',
                                        f'present_{self.sec1.pk}_{self.alice.pk}': 'on'})
        self.assertEqual(r.status_code, 302)
        rec = {a.student_id: a.present for a in AttendanceRecord.objects.filter(section=self.sec1, date=self.today)}
        self.assertEqual(rec, {self.alice.pk: True, self.bob.pk: False})
        self.assertTrue(AttendanceSession.objects.filter(section=self.sec1, date=self.today).exists())

    def test_cannot_write_attendance_for_another_teachers_section(self):
        self.login(self.t1.user)
        self.client.post(self.url + '?all=1', {'date': self.today.isoformat(), 'all': '1',
                                               f'include_{self.sec2.pk}': 'on', f'present_{self.sec2.pk}_{self.carl.pk}': 'on'})
        self.assertFalse(AttendanceRecord.objects.filter(section=self.sec2).exists())

    def test_resaving_is_idempotent_and_updates(self):
        self.login(self.t1.user)
        for present in (True, False):
            data = {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on'}
            if present:
                data[f'present_{self.sec1.pk}_{self.alice.pk}'] = 'on'
            self.client.post(self.url, data)
        self.assertEqual(AttendanceRecord.objects.filter(section=self.sec1, date=self.today).count(), 2)
        self.assertFalse(AttendanceRecord.objects.get(section=self.sec1, date=self.today, student=self.alice).present)

    def test_finalise_locks_for_teacher_but_not_admin(self):
        self.login(self.t1.user)
        base = {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on', f'present_{self.sec1.pk}_{self.alice.pk}': 'on'}
        self.client.post(self.url, {**base, 'finalise': 'on'})
        self.assertFalse(AttendanceSession.objects.get(section=self.sec1, date=self.today).is_open)
        self.client.post(self.url, {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on'})   # try: everyone absent
        self.assertTrue(AttendanceRecord.objects.get(section=self.sec1, date=self.today, student=self.alice).present)
        self.login(self.root)
        self.client.post(self.url + '?all=1', {'date': self.today.isoformat(), 'all': '1', f'include_{self.sec1.pk}': 'on'})
        self.assertFalse(AttendanceRecord.objects.get(section=self.sec1, date=self.today, student=self.alice).present)

    def test_old_single_section_screen_also_respects_the_lock(self):
        self.login(self.t1.user)
        self.client.post(self.url, {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on',
                                    f'present_{self.sec1.pk}_{self.alice.pk}': 'on', 'finalise': 'on'})
        self.client.post('/attendance/bulk/', {'section': self.sec1.pk, 'date': self.today.isoformat()})
        self.assertTrue(AttendanceRecord.objects.get(section=self.sec1, date=self.today, student=self.alice).present)

    def test_present_all_only_for_unmarked_classes(self):
        out = T.mark_all_present_where_unmarked(self.t1.user)
        self.assertEqual((out['marked_sections'], out['marked_students']), (1, 2))
        self.assertTrue(all(a.present for a in AttendanceRecord.objects.filter(section=self.sec1)))
        self.assertFalse(AttendanceRecord.objects.filter(section=self.sec2).exists())     # not mine
        again = T.mark_all_present_where_unmarked(self.t1.user)
        self.assertEqual(again['marked_sections'], 0)
        self.assertEqual(again['skipped_sections'], 1)

    def test_present_all_does_not_overwrite_a_marked_class(self):
        AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=self.today, present=False, semester=self.sem)
        self.assertEqual(T.mark_all_present_where_unmarked(self.t1.user)['marked_sections'], 0)
        self.assertFalse(AttendanceRecord.objects.get(student=self.alice, section=self.sec1).present)

    def test_future_date_is_refused(self):
        self.login(self.t1.user)
        d = (self.today + datetime.timedelta(days=2)).isoformat()
        self.client.post(self.url, {'date': d, f'include_{self.sec1.pk}': 'on'})
        self.assertFalse(AttendanceRecord.objects.exists())

    def test_students_and_anonymous_cannot_use_it(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.login(self.alice.user)
        for u in (self.url, '/teacher/automation/', f'/teacher/marks/{self.sec1.pk}/'):
            self.assertEqual(self.client.get(u).status_code, 403, u)


class TeacherMarksTests(Base):
    def setUp(self):
        super().setUp()
        self.sc, self.mid, self.fin = self.scheme(self.sec1.course)
        self.ra = CourseRegistration.objects.get(student=self.alice, section=self.sec1)
        self.rb = CourseRegistration.objects.get(student=self.bob, section=self.sec1)
        self.url = f'/teacher/marks/{self.sec1.pk}/'

    def post(self, **fields):
        return self.client.post(self.url, {'action': 'save', **fields})

    def key(self, reg, comp):
        return f'mark_{reg.pk}_{comp.pk}'

    def test_raw_marks_in_total_and_grade_calculated_out(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '25', self.key(self.ra, self.fin): '60'})
        row = T.marks_sheet(self.sec1)['rows'][0]
        self.assertEqual(row['student'], self.alice)
        self.assertEqual(row['total'], Decimal('85.00'))          # 25/30*30 + 60/70*70
        self.assertTrue(row['complete'])
        self.assertEqual(row['grade'], 'A')                       # default scale: 85-89.99 = A

    def test_incomplete_student_has_no_grade(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '25'})
        row = T.marks_sheet(self.sec1)['rows'][0]
        self.assertFalse(row['complete']); self.assertEqual(row['grade'], '')

    def test_out_of_range_and_non_numeric_rejected(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '31', self.key(self.rb, self.mid): 'abc'})
        self.assertFalse(AssessmentMark.objects.exists())

    def test_blank_cell_keeps_existing_mark(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '20'})
        self.post(**{self.key(self.ra, self.mid): ''})
        self.assertEqual(AssessmentMark.objects.get(registration=self.ra, component=self.mid).raw_marks, Decimal('20.00'))

    def test_other_teachers_marks_sheet_is_404(self):
        self.login(self.t2.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.post(self.url, {'action': 'save', self.key(self.ra, self.mid): '10'})
        self.assertFalse(AssessmentMark.objects.exists())

    def test_cannot_post_marks_for_a_registration_in_a_different_section(self):
        other = CourseRegistration.objects.get(student=self.carl, section=self.sec2)
        self.login(self.t1.user)
        self.post(**{self.key(other, self.mid): '10'})
        self.assertFalse(AssessmentMark.objects.exists())

    def test_no_scheme_means_no_entry(self):
        self.login(self.t1.user)
        r = self.client.post(f'/teacher/marks/{self.sec1b.pk}/', {'action': 'save', 'mark_1_1': '5'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AssessmentMark.objects.exists())

    def test_submit_only_complete_and_then_locked(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '25', self.key(self.ra, self.fin): '60', self.key(self.rb, self.mid): '10'})
        self.client.post(self.url, {'action': 'submit'})
        self.assertEqual(ResultPublication.objects.get(registration=self.ra).status, 'teacher_submitted')
        self.assertFalse(ResultPublication.objects.filter(registration=self.rb).exists())    # incomplete stays editable
        self.post(**{self.key(self.ra, self.mid): '1'})
        self.assertEqual(AssessmentMark.objects.get(registration=self.ra, component=self.mid).raw_marks, Decimal('25.00'))
        self.post(**{self.key(self.rb, self.fin): '50'})
        self.assertTrue(AssessmentMark.objects.filter(registration=self.rb, component=self.fin).exists())

    def test_reopened_result_is_editable_and_resubmittable(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '25', self.key(self.ra, self.fin): '60'})
        self.client.post(self.url, {'action': 'submit'})
        ResultWorkflowService.reopen(self.root, ResultPublication.objects.get(registration=self.ra), 'Typo in midterm')
        self.post(**{self.key(self.ra, self.mid): '27'})
        self.assertEqual(AssessmentMark.objects.get(registration=self.ra, component=self.mid).raw_marks, Decimal('27.00'))
        self.client.post(self.url, {'action': 'submit'})
        self.assertEqual(ResultPublication.objects.get(registration=self.ra).status, 'teacher_submitted')

    def test_dashboard_flags_results_ready_to_submit(self):
        self.login(self.t1.user)
        self.post(**{self.key(self.ra, self.mid): '25', self.key(self.ra, self.fin): '60'})
        labels = [i['label'] for i in self.client.get(reverse('teacher-dashboard')).context['action_items']]
        self.assertTrue(any('ready to submit' in l for l in labels), labels)


class ResultWorkflowTests(Base):
    def setUp(self):
        super().setUp()
        self.sc, self.mid, self.fin = self.scheme(self.sec1.course)
        self.ra = CourseRegistration.objects.get(student=self.alice, section=self.sec1)
        self.login(self.t1.user)
        self.client.post(f'/teacher/marks/{self.sec1.pk}/', {'action': 'save', f'mark_{self.ra.pk}_{self.mid.pk}': '25', f'mark_{self.ra.pk}_{self.fin.pk}': '60'})
        self.client.post(f'/teacher/marks/{self.sec1.pk}/', {'action': 'submit'})
        self.pub = ResultPublication.objects.get(registration=self.ra)

    def officer(self, name, code):
        u = self.user(name, 'staff')
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code=code))
        return u

    def test_teacher_and_student_cannot_open_the_workflow(self):
        for u in (self.t1.user, self.alice.user):
            self.login(u)
            self.assertEqual(self.client.get('/results/workflow/').status_code, 403)
            self.client.post('/results/workflow/', {'pub': self.pub.pk})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'teacher_submitted')

    def test_super_admin_walks_all_stages_and_student_is_notified_at_publish(self):
        self.login(self.root)
        for expected in ('department_verified', 'exam_verified', 'published'):
            self.client.post('/results/workflow/', {'pub': self.pub.pk})
            self.pub.refresh_from_db(); self.assertEqual(self.pub.status, expected)
        self.assertTrue(Notification.objects.filter(user=self.alice.user, title='Result published').exists())
        self.assertIsNotNone(AssessmentMark.objects.filter(registration=self.ra).first().published_at)
        self.assertEqual(ResultWorkflowService.queue(self.root), [])   # published results leave the queue

    def test_hod_can_verify_but_not_approve_or_publish(self):
        hod = self.officer('hod1', 'hod')
        self.login(hod)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'department_verified')
        self.client.post('/results/workflow/', {'pub': self.pub.pk})           # needs 'approve' -> denied
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'department_verified')

    def test_exam_controller_only_publishes_and_cannot_do_the_exam_office_stage(self):
        # Super admin (break-glass: nobody holds verify/approve yet) takes it to exam_verified ...
        self.client.force_login(self.root)
        for _ in range(2):
            self.client.post('/results/workflow/', {'pub': self.pub.pk})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'exam_verified')
        ec = self.officer('ec1', 'exam_controller')
        self.login(ec)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})      # ... the Controller publishes
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'published')

    def test_exam_controller_cannot_approve_in_the_exam_offices_place(self):
        self.client.force_login(self.root)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})      # department_verified
        ec = self.officer('ec2', 'exam_controller')
        self.login(ec)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})      # needs results.approve -> denied
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'department_verified')

    def test_finance_officer_cannot_touch_results(self):
        fin = self.officer('fin1', 'finance_officer')
        self.login(fin)
        self.assertEqual(self.client.get('/results/workflow/').status_code, 403)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'teacher_submitted')

    def test_cannot_skip_a_stage_by_posting_twice_for_a_different_stage(self):
        # even a super admin only moves one stage per action
        self.login(self.root)
        self.client.post('/results/workflow/', {'pub': self.pub.pk})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'department_verified')

    def test_reopen_requires_reason_and_permission_and_is_audited(self):
        from core.models import AuditLog
        hod = self.officer('hod2', 'hod')                      # lacks 'override'
        self.login(hod)
        self.client.post('/results/workflow/', {'pub': self.pub.pk, 'action': 'reopen', 'reason': 'x'})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'teacher_submitted')
        self.login(self.root)
        self.client.post('/results/workflow/', {'pub': self.pub.pk, 'action': 'reopen', 'reason': '  '})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'teacher_submitted')
        self.client.post('/results/workflow/', {'pub': self.pub.pk, 'action': 'reopen', 'reason': 'Midterm typo'})
        self.pub.refresh_from_db(); self.assertEqual(self.pub.status, 'reopened')
        self.assertTrue(AuditLog.objects.filter(action='RESULT_REOPENED', reason='Midterm typo').exists())


class TeacherHousekeepingTests(Base):
    def test_low_attendance_alerts_only_my_students_once(self):
        SiteSettings.objects.update_or_create(pk=1, defaults={'minimum_attendance_percent': 80})
        for i in range(4):
            d = self.today - datetime.timedelta(days=i + 1)
            AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=d, present=(i == 0), semester=self.sem)
            AttendanceRecord.objects.create(student=self.carl, section=self.sec2, date=d, present=False, semester=self.sem)
        self.assertEqual(T.low_attendance_alerts(self.t1.user, dry_run=True)['low_attendance'], 1)
        self.assertEqual(Notification.objects.count(), 0)
        T.low_attendance_alerts(self.t1.user); T.low_attendance_alerts(self.t1.user)
        self.assertEqual(Notification.objects.filter(user=self.alice.user, title='Low attendance warning').count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.carl.user).exists())      # other teacher's student

    def test_assignment_reminder_skips_students_who_already_submitted(self):
        a = Assignment.objects.create(section=self.sec1, title='HW1', due_date=timezone.now() + datetime.timedelta(hours=10))
        a.submissions.create(student=self.alice, text_answer='done')
        self.assertEqual(T.assignment_reminders(self.t1.user)['assignment_reminders'], 1)
        self.assertTrue(Notification.objects.filter(user=self.bob.user, title='Assignment due soon').exists())
        self.assertFalse(Notification.objects.filter(user=self.alice.user, title='Assignment due soon').exists())

    def test_run_is_recorded_like_any_automation_run(self):
        self.login = self.client.force_login(self.t1.user)
        r = self.client.post('/teacher/automation/', {})            # dry_run unchecked -> live
        self.assertEqual(r.status_code, 302)
        run = AutomationRun.objects.get(trigger=f'teacher:{self.t1.user.pk}')
        self.assertIn(run.status, ('completed',))
        self.assertEqual({t.name for t in run.tasks.all()}, {'low_attendance_alerts', 'assignment_reminders'})

    def test_teacher_automation_page_renders(self):
        self.client.force_login(self.t1.user)
        r = self.client.get('/teacher/automation/')
        self.assertContains(r, 'Classes today'); self.assertContains(r, 'CS101')
        self.assertNotContains(r, 'CS201')


class StudentAutomationTests(Base):
    def test_semester_challan_is_created_once(self):
        self.client.force_login(self.carl.user)
        self.client.post('/student/automation/', {'action': 'challan'})
        self.client.post('/student/automation/', {'action': 'challan'})
        from finance.models import Invoice
        self.assertEqual(Invoice.objects.filter(student=self.carl, category='semester').count(), 1)
        self.assertEqual(Invoice.objects.get(student=self.carl, category='semester').amount, Decimal('50000'))

    def test_register_action_uses_the_eligibility_service(self):
        self.client.force_login(self.bob.user)
        with mock.patch('core.services.academic.AcademicEligibilityService.auto_assign_current_courses',
                        return_value={'created': [self.register(self.bob, self.sec1b)], 'skipped': []}) as m:
            r = self.client.post('/student/automation/', {'action': 'register'}, follow=True)
        m.assert_called_once()
        self.assertContains(r, 'CS102')

    def test_overview_reports_real_attendance_shortfall(self):
        SiteSettings.objects.update_or_create(pk=1, defaults={'minimum_attendance_percent': 80})
        for i in range(3):
            AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=self.today - datetime.timedelta(days=i + 1),
                                            present=(i == 0), semester=self.sem)
        o = StudentAutomationService.overview(self.alice)
        self.assertEqual([s['course'].code for s in o['shortfalls']], ['CS101'])
        self.assertEqual(StudentAutomationService.overview(self.bob)['shortfalls'], [])

    def test_page_renders_for_student_and_is_forbidden_for_teacher(self):
        self.client.force_login(self.alice.user)
        self.assertContains(self.client.get('/student/automation/'), 'My Smart Actions')
        self.client.force_login(self.t1.user)
        self.assertEqual(self.client.get('/student/automation/').status_code, 403)

    def test_dashboards_link_to_the_new_screens(self):
        self.client.force_login(self.alice.user)
        self.assertContains(self.client.get(reverse('student-dashboard')), '/student/automation/')
        self.client.force_login(self.t1.user)
        self.assertContains(self.client.get(reverse('teacher-dashboard')), '/teacher/automation/')


class AttendanceCorrectionTests(Base):
    url = '/teacher/attendance/today/'

    def finalise(self):
        self.client.force_login(self.t1.user)
        self.client.post(self.url, {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on',
                                    f'present_{self.sec1.pk}_{self.alice.pk}': 'on', 'finalise': 'on'})
        return AttendanceSession.objects.get(section=self.sec1, date=self.today)

    def ask(self, user, session, reason='Marked Bob absent by mistake'):
        self.client.force_login(user)
        return self.client.post(f'/attendance/corrections/request/{session.pk}/', {'reason': reason})

    def officer(self, name, grants):
        from governance.models import RolePermission
        u = self.user(name, 'staff')
        role = Role.objects.create(code=f'r_{name}', name=name)
        for module, action in grants:
            RolePermission.objects.create(role=role, module=module, action=action)
        RoleAssignment.objects.create(user=u, role=role)
        return u

    def test_full_cycle_request_approve_reopen_edit_audit(self):
        from attendance.models import AttendanceCorrectionRequest
        from core.models import AuditLog
        s = self.finalise()
        self.ask(self.t1.user, s)
        req = AttendanceCorrectionRequest.objects.get()
        self.assertEqual(req.status, 'pending'); self.assertFalse(s.is_open)
        self.client.force_login(self.root)
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'approve'})
        s.refresh_from_db(); req.refresh_from_db()
        self.assertTrue(s.is_open); self.assertEqual(req.status, 'approved'); self.assertEqual(req.decided_by, self.root)
        self.assertTrue(AuditLog.objects.filter(action='ATTENDANCE_CORRECTION_APPROVED').exists())
        self.assertTrue(Notification.objects.filter(user=self.t1.user, title='Attendance correction approved').exists())
        # the teacher can edit again
        self.client.force_login(self.t1.user)
        self.client.post(self.url, {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on', f'present_{self.sec1.pk}_{self.bob.pk}': 'on'})
        self.assertTrue(AttendanceRecord.objects.get(section=self.sec1, date=self.today, student=self.bob).present)

    def test_reject_needs_note_and_keeps_sheet_locked(self):
        from attendance.models import AttendanceCorrectionRequest
        s = self.finalise(); self.ask(self.t1.user, s)
        req = AttendanceCorrectionRequest.objects.get()
        self.client.force_login(self.root)
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'reject', 'note': ' '})
        req.refresh_from_db(); self.assertEqual(req.status, 'pending')
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'reject', 'note': 'Evidence insufficient'})
        req.refresh_from_db(); s.refresh_from_db()
        self.assertEqual(req.status, 'rejected'); self.assertFalse(s.is_open)

    def test_cannot_request_for_open_sheet_without_reason_twice_or_for_others(self):
        from attendance.models import AttendanceCorrectionRequest
        open_sheet = AttendanceSession.objects.create(section=self.sec1, semester=self.sem, date=self.today, created_by=self.t1.user)
        self.ask(self.t1.user, open_sheet)
        self.assertEqual(AttendanceCorrectionRequest.objects.count(), 0)          # not finalised
        open_sheet.is_open = False; open_sheet.save()
        self.ask(self.t1.user, open_sheet, reason='  ')
        self.assertEqual(AttendanceCorrectionRequest.objects.count(), 0)          # no reason
        self.ask(self.t1.user, open_sheet); self.ask(self.t1.user, open_sheet)
        self.assertEqual(AttendanceCorrectionRequest.objects.count(), 1)          # no duplicates
        self.assertEqual(self.ask(self.t2.user, open_sheet).status_code, 403)     # someone else's section
        self.assertEqual(self.ask(self.alice.user, open_sheet).status_code, 403)

    def test_only_people_with_attendance_approve_can_decide(self):
        from attendance.models import AttendanceCorrectionRequest
        s = self.finalise(); self.ask(self.t1.user, s)
        req = AttendanceCorrectionRequest.objects.get()
        for who in (self.t1.user, self.t2.user, self.alice.user, self.officer('viewer', [('attendance', 'view')]),
                    self.officer('fin', [('finance', 'approve')])):
            self.client.force_login(who)
            self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'approve'})
        req.refresh_from_db(); self.assertEqual(req.status, 'pending')
        ok = self.officer('approver', [('attendance', 'approve')])
        self.client.force_login(ok)
        self.assertEqual(self.client.get('/attendance/corrections/').status_code, 200)
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'approve'})
        req.refresh_from_db(); self.assertEqual(req.status, 'approved')

    def test_decided_request_cannot_be_decided_again(self):
        from attendance.models import AttendanceCorrectionRequest
        s = self.finalise(); self.ask(self.t1.user, s)
        req = AttendanceCorrectionRequest.objects.get()
        self.client.force_login(self.root)
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'approve'})
        self.client.post('/attendance/corrections/', {'req': req.pk, 'decision': 'reject', 'note': 'changed my mind'})
        req.refresh_from_db(); self.assertEqual(req.status, 'approved')

    def test_teacher_sheet_offers_the_request_button_only_when_locked(self):
        self.finalise()
        r = self.client.get(self.url)
        self.assertContains(r, 'Request correction')
        self.ask(self.t1.user, AttendanceSession.objects.get(section=self.sec1, date=self.today))
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url)
        self.assertContains(r, 'correction request is pending'); self.assertNotContains(r, 'Request correction</button>')


class PublishedResultReachesStudentTests(Base):
    """A result published via the assessment workflow must show up where students and GPA actually read."""

    def setUp(self):
        super().setUp()
        self.sc, self.mid, self.fin = self.scheme(self.sec1.course)
        self.ra = CourseRegistration.objects.get(student=self.alice, section=self.sec1)
        self.mk = f'/teacher/marks/{self.sec1.pk}/'
        self.enter(25, 60)

    def enter(self, mid, fin):
        self.client.force_login(self.t1.user)
        self.client.post(self.mk, {'action': 'save', f'mark_{self.ra.pk}_{self.mid.pk}': str(mid), f'mark_{self.ra.pk}_{self.fin.pk}': str(fin)})
        self.client.post(self.mk, {'action': 'submit'})

    def advance_to_published(self):
        pub = ResultPublication.objects.get(registration=self.ra)
        for _ in range(3):
            ResultWorkflowService.advance(self.root, ResultPublication.objects.get(pk=pub.pk))
        return ResultPublication.objects.get(pk=pub.pk)

    def entry(self):
        from exams.models import GradeEntry
        return GradeEntry.objects.filter(registration=self.ra, exam__name='Final Result (Assessment Scheme)').first()

    def test_nothing_reaches_the_ledger_or_student_before_publication(self):
        self.assertIsNone(self.entry())
        self.client.force_login(self.alice.user)
        page = self.client.get(reverse('student-dashboard'))
        self.assertContains(page, 'Awaiting verification')
        self.assertNotContains(page, '85.00%')
        self.assertNotContains(self.client.get(reverse('result-checker')), 'Final Result (Assessment Scheme)')

    def test_publication_writes_grade_entry_visible_on_results_and_in_cgpa(self):
        from core.services.academic import AcademicProgressService
        self.advance_to_published()
        e = self.entry()
        self.assertEqual((e.marks, e.grade), (Decimal('85.00'), 'A'))
        self.client.force_login(self.alice.user)
        r = self.client.get(reverse('result-checker'))
        self.assertContains(r, 'CS101'); self.assertContains(r, '85')
        self.assertEqual(AcademicProgressService.calculate(self.alice)['cgpa'], Decimal('4.00'))
        dash = self.client.get(reverse('student-dashboard'))
        self.assertContains(dash, '85.00%'); self.assertContains(dash, 'Published')

    def test_other_student_does_not_see_it(self):
        self.advance_to_published()
        self.client.force_login(self.bob.user)
        self.assertNotContains(self.client.get(reverse('result-checker')), 'CS101 ')
        from exams.models import GradeEntry
        self.assertFalse(GradeEntry.objects.filter(student=self.bob).exists())

    def test_reopen_removes_ledger_entry_and_preserves_old_value_in_audit(self):
        from core.models import AuditLog
        pub = self.advance_to_published()
        ResultWorkflowService.reopen(self.root, pub, 'Final paper was mis-scored')
        self.assertIsNone(self.entry())
        log = AuditLog.objects.filter(action='RESULT_REOPENED').latest('id')
        self.assertEqual(log.changes['published_grade'][0], 'A')
        self.assertEqual(log.changes['published_marks'][0], '85.00')
        self.client.force_login(self.alice.user)
        self.assertNotContains(self.client.get(reverse('student-dashboard')), '85.00%')

    def test_correct_and_republish_updates_grade_and_cgpa(self):
        from core.services.academic import AcademicProgressService
        pub = self.advance_to_published()
        ResultWorkflowService.reopen(self.root, pub, 'Re-evaluation approved')
        self.enter(25, 40)                                    # teacher corrects the final: 25 + 40 = 65 -> C
        self.assertEqual(ResultPublication.objects.get(registration=self.ra).status, 'teacher_submitted')
        self.advance_to_published()
        self.assertEqual((self.entry().marks, self.entry().grade), (Decimal('65.00'), 'C'))
        self.assertEqual(AcademicProgressService.calculate(self.alice)['cgpa'], Decimal('2.00'))

    def test_synced_result_supersedes_a_legacy_entry_for_the_same_course(self):
        from exams.models import ExamSession, GradeEntry, canonical_grades
        legacy_exam = ExamSession.objects.create(name='Old exam', course=self.sec1.course, semester=self.sem, date=self.today)
        GradeEntry.objects.create(student=self.alice, exam=legacy_exam, registration=self.ra, marks=Decimal('50'))
        self.advance_to_published()
        grades = canonical_grades(GradeEntry.objects.filter(student=self.alice).select_related('exam__course', 'exam__semester'))
        cs101 = [g for g in grades if g.exam.course_id == self.sec1.course_id]
        self.assertEqual(len(cs101), 1)                       # one result per course, not two
        self.assertEqual(cs101[0].grade, 'A')

    def test_reopened_result_can_only_restart_from_teacher_submission(self):
        from exams.services_dynamic import ResultPublicationService
        pub = self.advance_to_published()
        ResultWorkflowService.reopen(self.root, pub, 'x')
        with self.assertRaises(ValueError):
            ResultPublicationService.advance(self.ra, 'department_verified', user=self.root)


class LegacyGradeFormGuardTests(Base):
    """A scheme-graded course must not also be graded through the instant legacy form."""

    def setUp(self):
        super().setUp()
        from exams.models import ExamSession
        self.exam = ExamSession.objects.create(name='Quick exam', course=self.sec1.course, semester=self.sem, date=self.today)
        self.exam_other = ExamSession.objects.create(name='Quick exam', course=self.sec1b.course, semester=self.sem, date=self.today)

    def post(self, user, exam, student):
        self.client.force_login(user)
        return self.client.post('/exams/results/add/', {'student': student.pk, 'exam': exam.pk, 'marks': '70', 'attempt_type': 'regular'})

    def test_teacher_is_redirected_to_marks_sheet_when_course_has_scheme(self):
        from exams.models import GradeEntry
        self.scheme(self.sec1.course)
        r = self.post(self.t1.user, self.exam, self.alice)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], f'/teacher/marks/{self.sec1.pk}/')
        self.assertFalse(GradeEntry.objects.exists())

    def test_course_without_scheme_still_uses_legacy_form(self):
        from exams.models import GradeEntry
        self.post(self.t1.user, self.exam_other, self.alice)
        self.assertTrue(GradeEntry.objects.filter(student=self.alice, exam=self.exam_other).exists())

    def test_edit_of_existing_entry_is_also_redirected(self):
        from exams.models import GradeEntry
        g = GradeEntry.objects.create(student=self.alice, exam=self.exam, marks=Decimal('60'))
        self.scheme(self.sec1.course)
        self.client.force_login(self.t1.user)
        r = self.client.get(f'/exams/results/{g.pk}/edit/')
        self.assertEqual(r.status_code, 302); self.assertIn('/teacher/marks/', r['Location'])

    def test_super_admin_is_not_blocked(self):
        from exams.models import GradeEntry
        self.scheme(self.sec1.course)
        self.post(self.root, self.exam, self.alice)
        self.assertTrue(GradeEntry.objects.filter(student=self.alice, exam=self.exam).exists())
