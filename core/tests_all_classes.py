"""All-classes attendance totals and marks entry with filters: teacher scope, admin parity, safety."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicSession, CourseRegistration, Semester
from attendance.models import AttendanceRecord
from core.models import SiteSettings
from core.services.role_automation import TeacherAutomationService as T
from core.tests_role_automation import Base
from exams.models import AssessmentMark, ResultPublication


class AttendanceSummaryTests(Base):
    url = '/teacher/attendance/summary/'

    def setUp(self):
        super().setUp()
        SiteSettings.objects.update_or_create(pk=1, defaults={'minimum_attendance_percent': 75})
        for i, pres in enumerate((True, True, False)):                        # alice in CS101: 2 of 3 = 66.7%
            d = self.today - datetime.timedelta(days=i + 1)
            AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=d, present=pres, semester=self.sem)
            AttendanceRecord.objects.create(student=self.bob, section=self.sec1, date=d, present=False, semester=self.sem)   # bob 0%
            AttendanceRecord.objects.create(student=self.carl, section=self.sec2, date=d, present=True, semester=self.sem)

    def blocks(self, user, **kw):
        return {b['section'].course.code: b for b in T.attendance_summary(user, **kw)['blocks']}

    def test_totals_per_class_per_student_and_overall(self):
        d = T.attendance_summary(self.t1.user)
        b = {x['section'].course.code: x for x in d['blocks']}
        self.assertEqual(set(b), {'CS101', 'CS102'})                          # never CS201 (other teacher)
        cs = b['CS101']
        self.assertEqual((cs['sessions'], cs['students'], cs['avg'], cs['low_count']), (3, 2, 33.3, 2))
        rows = {r['student'].pk: r for r in cs['rows']}
        self.assertEqual((rows[self.alice.pk]['present'], rows[self.alice.pk]['total'], rows[self.alice.pk]['pct']), (2, 3, 66.7))
        self.assertEqual(rows[self.bob.pk]['pct'], 0.0)
        self.assertIsNone(b['CS102']['rows'][0]['pct'])                       # no attendance yet: shown as none, not 0
        self.assertEqual(d['totals']['classes'], 2)

    def test_below_minimum_search_subject_and_class_filters(self):
        t1 = self.t1.user
        self.assertEqual([r['student'].full_name for r in self.blocks(t1, below_only=True)['CS101']['rows']].__len__(), 2)
        self.assertEqual([r['student'] for r in self.blocks(t1, q='bob')['CS101']['rows']], [self.bob])
        self.assertEqual([r['student'] for r in self.blocks(t1, q='A-bob')['CS101']['rows']], [self.bob])      # admission no. search
        self.assertEqual(set(self.blocks(t1, course_id=self.sec1b.course_id)), {'CS102'})
        self.assertEqual(set(self.blocks(t1, section_id=self.sec1.pk)), {'CS101'})

    def test_date_range_filter(self):
        only_yesterday = self.blocks(self.t1.user, date_from=self.today - datetime.timedelta(days=1),
                                     date_to=self.today - datetime.timedelta(days=1))['CS101']
        self.assertEqual(only_yesterday['sessions'], 1)
        self.assertEqual({r['student'].pk: r['total'] for r in only_yesterday['rows']}, {self.alice.pk: 1, self.bob.pk: 1})

    def test_other_semesters_are_never_mixed_in(self):
        sess = AcademicSession.objects.first()
        old = Semester.objects.create(name='Spring 2026', session=sess, semester_number=0,
                                      start_date=self.today - datetime.timedelta(days=200), end_date=self.today - datetime.timedelta(days=120))
        AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=self.today - datetime.timedelta(days=150),
                                        present=False, semester=old)
        cs = self.blocks(self.t1.user)['CS101']
        self.assertEqual(next(r for r in cs['rows'] if r['student'] == self.alice)['total'], 3)   # still 3, not 4
        self.assertEqual(T.attendance_summary(self.t1.user, semester=old)['blocks'][0]['sessions'], 1)

    def test_teacher_cannot_widen_scope_with_teacher_or_foreign_ids(self):
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url, {'teacher': self.t2.pk})
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS101', 'CS102'})
        r = self.client.get(self.url, {'section': self.sec2.pk, 'course': self.sec2.course_id})
        self.assertEqual(r.context['blocks'], [])
        self.assertEqual(list(r.context['teachers']), [])                      # no teacher dropdown for teachers

    def test_admin_sees_every_class_and_can_filter_by_teacher(self):
        self.client.force_login(self.root)
        r = self.client.get(self.url)
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS101', 'CS102', 'CS201'})
        r = self.client.get(self.url, {'teacher': self.t2.pk})
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS201'})
        self.assertTrue(len(r.context['teachers']) >= 2)

    def test_page_renders_filters_and_numbers_and_blocks_students(self):
        self.client.force_login(self.t1.user)
        page = self.client.get(self.url)
        self.assertContains(page, 'Attendance — all classes'); self.assertContains(page, '66.7%'); self.assertContains(page, 'Below 75%')
        self.assertEqual(self.client.get(self.url, {'from': 'garbage', 'semester': 'x'}).status_code, 200)   # bad input tolerated
        self.client.force_login(self.alice.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_todays_sheet_subject_filter_and_save_under_filter(self):
        AttendanceRecord.objects.all().delete()
        self.client.force_login(self.t1.user)
        r = self.client.get('/teacher/attendance/today/', {'all': '1', 'course': self.sec1b.course_id})
        self.assertEqual({s['section'].course.code for s in r.context['sheets']}, {'CS102'})
        self.assertEqual(r.context['total_students'], 1)
        r = self.client.post('/teacher/attendance/today/', {'date': self.today.isoformat(), 'all': '1', 'course': self.sec1b.course_id,
                                                           f'include_{self.sec1b.pk}': 'on', f'present_{self.sec1b.pk}_{self.alice.pk}': 'on'})
        self.assertEqual(r.status_code, 302); self.assertIn(f'course={self.sec1b.course_id}', r['Location'])
        self.assertTrue(AttendanceRecord.objects.filter(section=self.sec1b, student=self.alice, present=True).exists())
        self.assertFalse(AttendanceRecord.objects.filter(section=self.sec1).exists())      # the filtered-out class untouched


class MarksAllClassesTests(Base):
    url = '/teacher/marks/'

    def setUp(self):
        super().setUp()
        self.s1, self.m1, self.f1 = self.scheme(self.sec1.course)       # CS101 (t1)
        self.s1b, self.m1b, self.f1b = self.scheme(self.sec1b.course)   # CS102 (t1)
        self.s2, self.m2, self.f2 = self.scheme(self.sec2.course)       # CS201 (t2)
        self.ra1 = CourseRegistration.objects.get(student=self.alice, section=self.sec1)
        self.rb1 = CourseRegistration.objects.get(student=self.bob, section=self.sec1)
        self.ra1b = CourseRegistration.objects.get(student=self.alice, section=self.sec1b)
        self.rc2 = CourseRegistration.objects.get(student=self.carl, section=self.sec2)

    def key(self, reg, comp):
        return f'mark_{reg.pk}_{comp.pk}'

    def msgs(self, r):
        return [str(m) for m in get_messages(r.wsgi_request)]

    def test_page_lists_every_class_of_mine_on_one_page_and_never_anothers(self):
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url)
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS101', 'CS102'})
        self.assertEqual(r.context['student_count'], 3)                       # alice+bob in CS101, alice in CS102
        self.assertNotContains(r, 'CS201')

    def test_classes_without_a_scheme_are_listed_as_skipped_not_hidden(self):
        AssessmentMark.objects.all().delete()
        self.s1b.is_active = False; self.s1b.save()
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url)
        self.assertEqual([s.course.code for s in r.context['skipped']], ['CS102'])
        self.assertContains(r, 'No assessment scheme yet for')

    def test_one_post_saves_marks_for_several_classes_with_calculated_totals(self):
        self.client.force_login(self.t1.user)
        r = self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '25', self.key(self.ra1, self.f1): '60',
                                        self.key(self.ra1b, self.m1b): '20', self.key(self.rb1, self.m1): '10'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AssessmentMark.objects.count(), 4)
        row = next(x for x in T.marks_sheet(self.sec1)['rows'] if x['student'] == self.alice)
        self.assertEqual((row['total'], row['grade']), (Decimal('85.00'), 'A'))     # calculated, never typed
        self.assertTrue(any('Saved 4 mark' in m for m in self.msgs(r)))

    def test_marks_for_a_class_i_do_not_teach_are_refused_and_reported(self):
        self.client.force_login(self.t1.user)
        r = self.client.post(self.url, {'action': 'save', self.key(self.rc2, self.m2): '28', self.key(self.ra1, self.m1): '20'})
        self.assertFalse(AssessmentMark.objects.filter(registration=self.rc2).exists())
        self.assertTrue(AssessmentMark.objects.filter(registration=self.ra1).exists())
        self.assertTrue(any('you do not teach' in m for m in self.msgs(r)))

    def test_invalid_marks_rejected_valid_ones_in_the_same_post_still_saved(self):
        self.client.force_login(self.t1.user)
        r = self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '99', self.key(self.rb1, self.m1): 'abc',
                                        self.key(self.ra1b, self.m1b): '15'})
        self.assertEqual(AssessmentMark.objects.count(), 1)
        self.assertEqual(AssessmentMark.objects.get().raw_marks, Decimal('15.00'))
        self.assertTrue(any('outside' in m for m in self.msgs(r)) and any('not a number' in m for m in self.msgs(r)))

    def test_status_filter_incomplete_ready_submitted(self):
        self.client.force_login(self.t1.user)
        self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '25', self.key(self.ra1, self.f1): '60',     # alice complete
                                    self.key(self.rb1, self.m1): '10'})                                                       # bob incomplete
        names = lambda status: sorted(r['student'].full_name for b in self.client.get(self.url, {'status': status}).context['blocks'] for r in b['sheet']['rows'])
        self.assertIn('Alice', names('ready')); self.assertNotIn('Bob', names('ready'))
        self.assertIn('Bob', names('incomplete'))
        self.client.post(self.url, {'action': 'submit', 'sections': [self.sec1.pk]})
        self.assertEqual(names('submitted'), ['Alice'])
        self.assertNotIn('Alice', names('ready'))

    def test_student_search_and_course_filter(self):
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url, {'q': 'bob'})
        self.assertEqual([(b['section'].course.code, len(b['sheet']['rows'])) for b in r.context['blocks']], [('CS101', 1)])
        r = self.client.get(self.url, {'course': self.sec1b.course_id})
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS102'})

    def test_submit_all_covers_listed_classes_only_and_ignores_foreign_ids(self):
        self.client.force_login(self.t1.user)
        self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '25', self.key(self.ra1, self.f1): '60',
                                    self.key(self.ra1b, self.m1b): '20', self.key(self.ra1b, self.f1b): '40'})
        AssessmentMark.objects.create(registration=self.rc2, component=self.m2, raw_marks=Decimal('20'))
        AssessmentMark.objects.create(registration=self.rc2, component=self.f2, raw_marks=Decimal('40'))
        self.client.post(self.url, {'action': 'submit', 'sections': [self.sec1.pk, self.sec1b.pk, self.sec2.pk]})   # sec2 isn't mine
        self.assertEqual(ResultPublication.objects.filter(registration__in=[self.ra1, self.ra1b]).count(), 2)
        self.assertFalse(ResultPublication.objects.filter(registration=self.rc2).exists())

    def test_submitted_marks_stay_locked(self):
        self.client.force_login(self.t1.user)
        self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '25', self.key(self.ra1, self.f1): '60'})
        self.client.post(self.url, {'action': 'submit', 'sections': [self.sec1.pk]})
        r = self.client.post(self.url, {'action': 'save', self.key(self.ra1, self.m1): '1'})
        self.assertEqual(AssessmentMark.objects.get(registration=self.ra1, component=self.m1).raw_marks, Decimal('25.00'))
        self.assertTrue(any('locked' in m for m in self.msgs(r)))

    def test_filters_are_kept_after_saving(self):
        self.client.force_login(self.t1.user)
        r = self.client.post(self.url, {'action': 'save', 'qs': 'course=%d&status=incomplete' % self.sec1.course_id, self.key(self.ra1, self.m1): '5'})
        self.assertIn('course=', r['Location']); self.assertIn('status=incomplete', r['Location'])

    def test_admin_sees_all_teachers_and_can_filter_teacher_but_teacher_cannot(self):
        self.client.force_login(self.root)
        r = self.client.get(self.url)
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS101', 'CS102', 'CS201'})
        r = self.client.get(self.url, {'teacher': self.t2.pk})
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS201'})
        self.client.force_login(self.t1.user)
        r = self.client.get(self.url, {'teacher': self.t2.pk})
        self.assertEqual({b['section'].course.code for b in r.context['blocks']}, {'CS101', 'CS102'})

    def test_students_and_anonymous_are_refused(self):
        self.client.force_login(self.alice.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'action': 'save'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_sidebar_and_hub_link_to_the_new_pages(self):
        self.client.force_login(self.t1.user)
        page = self.client.get(reverse('teacher-automation'))
        self.assertContains(page, '/teacher/marks/'); self.assertContains(page, '/teacher/attendance/summary/')
        self.assertContains(self.client.get(reverse('teacher-dashboard')), '/teacher/attendance/summary/')


class TeacherDashboardActionTests(Base):
    def test_unmarked_classes_today_appear_as_an_action_item_and_disappear_once_marked(self):
        self.client.force_login(self.t1.user)
        labels = lambda: [i['label'] for i in self.client.get(reverse('teacher-dashboard')).context['action_items']]
        self.assertTrue(any('Attendance not taken yet today' in l and 'CS101' in l for l in labels()), labels())
        self.assertFalse(any('CS201' in l for l in labels()))                      # another teacher's class
        self.client.post('/teacher/attendance/today/', {'date': self.today.isoformat(), f'include_{self.sec1.pk}': 'on',
                                                       f'present_{self.sec1.pk}_{self.alice.pk}': 'on'})
        self.assertFalse(any('Attendance not taken yet today' in l for l in labels()), labels())
