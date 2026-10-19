"""Student dashboard modules: real data only, scoped to the signed-in student."""
import datetime
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from academics.models import CourseRegistration
from assignments.models import Assignment
from attendance.models import AttendanceRecord
from core.services.student_dashboard import StudentDashboardService as D
from core.tests_role_automation import Base
from exams.models import ExamSession, GradeEntry
from library.models import Book, BookLoan
from onlineclass.models import OnlineClass
from quizzes.models import Quiz, QuizAttempt


class DashboardModuleTests(Base):
    def titles(self, items):
        return [i['title'] for i in items]

    # ---- today's classes ----------------------------------------------------
    def test_todays_classes_only_my_registered_timetabled_sections(self):
        rows = D.todays_classes(self.alice, self.sem)
        self.assertEqual({r['course'].code for r in rows}, {'CS101'})       # CS102 not timetabled; CS201 not mine
        self.assertEqual({r['course'].code for r in D.todays_classes(self.carl, self.sem)}, {'CS201'})

    def test_class_state_now_later_done(self):
        tz = timezone.get_current_timezone()
        at = lambda h, m: timezone.make_aware(datetime.datetime.combine(self.today, datetime.time(h, m)), tz)
        self.assertEqual(D.todays_classes(self.alice, self.sem, now=at(9, 30))[0]['state'], 'now')
        self.assertEqual(D.todays_classes(self.alice, self.sem, now=at(7, 0))[0]['state'], 'later')
        self.assertEqual(D.todays_classes(self.alice, self.sem, now=at(15, 0))[0]['state'], 'done')

    def test_no_semester_or_no_registrations_means_empty(self):
        self.assertEqual(D.todays_classes(self.alice, None), [])
        stranger = self.student('stranger')
        self.assertEqual(D.build(stranger, self.sem)['todays_classes'], [])

    # ---- upcoming -----------------------------------------------------------
    def test_assignments_submitted_hidden_unsubmitted_listed_overdue_flagged(self):
        now = timezone.now()
        soon = Assignment.objects.create(section=self.sec1, title='Soon', due_date=now + datetime.timedelta(hours=10))
        done = Assignment.objects.create(section=self.sec1, title='Done', due_date=now + datetime.timedelta(days=2))
        late = Assignment.objects.create(section=self.sec1, title='Late', due_date=now - datetime.timedelta(days=2))
        ancient = Assignment.objects.create(section=self.sec1, title='Ancient', due_date=now - datetime.timedelta(days=30))
        far = Assignment.objects.create(section=self.sec1, title='Far', due_date=now + datetime.timedelta(days=60))
        done.submissions.create(student=self.alice, text_answer='x')
        items = D.upcoming(self.alice, self.sem)
        self.assertEqual(set(self.titles(items)), {'Soon', 'Late'})
        by = {i['title']: i for i in items}
        self.assertEqual(by['Late']['note'], 'overdue'); self.assertTrue(by['Late']['urgent']); self.assertTrue(by['Soon']['urgent'])
        self.assertEqual(self.titles(items), ['Late', 'Soon'])             # soonest first

    def test_other_courses_and_other_students_items_never_appear(self):
        Assignment.objects.create(section=self.sec2, title='Not mine', due_date=timezone.now() + datetime.timedelta(hours=5))
        self.assertEqual(D.upcoming(self.alice, self.sem), [])
        self.assertEqual(self.titles(D.upcoming(self.carl, self.sem)), ['Not mine'])

    def test_quizzes_published_and_not_yet_taken_only(self):
        q1 = Quiz.objects.create(section=self.sec1, title='Open quiz', is_published=True)
        Quiz.objects.create(section=self.sec1, title='Draft quiz', is_published=False)
        q3 = Quiz.objects.create(section=self.sec1, title='Taken quiz', is_published=True)
        QuizAttempt.objects.create(quiz=q3, student=self.alice, submitted_at=timezone.now(), score=3)
        self.assertEqual(self.titles(D.upcoming(self.alice, self.sem)), ['Open quiz'])
        self.assertEqual(self.titles(D.upcoming(self.bob, self.sem)), ['Open quiz', 'Taken quiz'])   # bob never attempted

    def test_online_classes_and_exams_listed_and_sync_session_is_not_an_exam(self):
        OnlineClass.objects.create(title='Revision', section=self.sec1, semester=self.sem, host=self.t1,
                                   scheduled_at=timezone.now() + datetime.timedelta(days=1))
        OnlineClass.objects.create(title='Ended one', section=self.sec1, semester=self.sem, host=self.t1,
                                   scheduled_at=timezone.now() + datetime.timedelta(days=1), status='ended')
        ExamSession.objects.create(name='Midterm', course=self.sec1.course, semester=self.sem, date=self.today + datetime.timedelta(days=5))
        ExamSession.objects.create(name='Final Result (Assessment Scheme)', course=self.sec1.course, semester=self.sem, date=self.today)
        ExamSession.objects.create(name='Other course exam', course=self.sec2.course, semester=self.sem, date=self.today + datetime.timedelta(days=5))
        items = D.upcoming(self.alice, self.sem)
        self.assertEqual(set(self.titles(items)), {'Revision', 'Midterm'})
        self.assertEqual({i['kind'] for i in items}, {'Online class', 'Exam'})

    def test_an_exam_i_already_have_a_grade_for_is_not_upcoming(self):
        ex = ExamSession.objects.create(name='Quiz exam', course=self.sec1.course, semester=self.sem, date=self.today + datetime.timedelta(days=1))
        GradeEntry.objects.create(student=self.alice, exam=ex, marks=Decimal('50'))
        self.assertEqual(D.upcoming(self.alice, self.sem), [])
        self.assertEqual(self.titles(D.upcoming(self.bob, self.sem)), ['Quiz exam'])      # bob has no grade for it

    # ---- degree progress ------------------------------------------------------
    def test_degree_progress_empty_before_any_result(self):
        d = D.degree_progress(self.alice)
        self.assertFalse(d['has_data']); self.assertEqual(d['trend'], [])

    def test_degree_progress_uses_real_grades(self):
        exam = ExamSession.objects.create(name='Final', course=self.sec1.course, semester=self.sem, date=self.today)
        GradeEntry.objects.create(student=self.alice, exam=exam, registration=CourseRegistration.objects.get(student=self.alice, section=self.sec1), marks=Decimal('85'))
        d = D.degree_progress(self.alice)
        self.assertTrue(d['has_data']); self.assertEqual(d['cgpa'], Decimal('4.0') if d['cgpa'] == 4 else d['cgpa'])
        self.assertEqual(float(d['cgpa']), 4.0)
        self.assertEqual([t['label'] for t in d['trend']], ['Fall 2026']); self.assertEqual(d['trend'][0]['width'], 100)
        self.assertIsNone(d['percent'])            # no curriculum credit total -> no invented progress bar

    # ---- library ----------------------------------------------------------------
    def test_library_shows_borrowed_only_and_flags_overdue(self):
        b1, b2, b3 = (Book.objects.create(title=t) for t in ('Algorithms', 'Networks', 'Old book'))
        BookLoan.objects.create(book=b1, student=self.alice, due_date=self.today + datetime.timedelta(days=3))
        BookLoan.objects.create(book=b2, student=self.alice, due_date=self.today - datetime.timedelta(days=2), fine_amount=Decimal('20'))
        BookLoan.objects.create(book=b3, student=self.alice, due_date=self.today, status='returned', returned_at=timezone.now())
        BookLoan.objects.create(book=b1, student=self.bob, due_date=self.today + datetime.timedelta(days=9))
        rows = D.library(self.alice)
        self.assertEqual([r['book'].title for r in rows], ['Networks', 'Algorithms'])
        self.assertTrue(rows[0]['overdue']); self.assertFalse(rows[1]['overdue'])
        self.assertEqual(rows[0]['fine'], Decimal('20'))


class DashboardPageTests(Base):
    def test_page_renders_modules_links_and_my_data_only(self):
        Assignment.objects.create(section=self.sec1, title='Lab report 1', due_date=timezone.now() + datetime.timedelta(hours=20))
        Assignment.objects.create(section=self.sec2, title='SECRET carl homework', due_date=timezone.now() + datetime.timedelta(hours=20))
        self.client.force_login(self.alice.user)
        r = self.client.get(reverse('student-dashboard'))
        self.assertEqual(r.status_code, 200)
        for text in ("Today's Classes", 'Upcoming', 'Degree Progress', 'Library', 'Lab report 1', 'CS101'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'SECRET carl homework')
        for url in ('/assignments/', '/quizzes/'):
            self.assertContains(r, f'href="{url}"')

    def test_empty_states_are_honest(self):
        newbie = self.student('newbie')
        self.client.force_login(newbie.user)
        r = self.client.get(reverse('student-dashboard'))
        self.assertContains(r, 'No classes scheduled for you today.')
        self.assertContains(r, 'Nothing due in the next two weeks.')
        self.assertContains(r, 'You have no borrowed books.')
        self.assertContains(r, 'No published results yet')

    def test_no_duplicate_id_card_tile_in_the_dashboard_grid(self):
        # The header button and the global sidebar already link to it; the tile grid must not add a third.
        self.client.force_login(self.alice.user)
        html = self.client.get(reverse('student-dashboard')).content.decode()
        self.assertNotIn(f'class="dash-card" href="{reverse("my-id-card")}"', html)
        self.assertIn(f'href="{reverse("my-id-card")}"', html)


class DashboardNavigationIsNotLostTests(Base):
    """Simplifying the dashboard must never remove a way to reach a screen."""
    LINKS = ['fees-list', 'verify-challan', 'hostel-apply', 'apply', 'scholarship-list', 'result-checker', 'submit-complaint',
             'student-automation', 'browse-sections', 'course-list', 'results', 'my-exam-slip', 'timetable-list', 'class-list',
             'assignment-list', 'quiz-list', 'attendance-list', 'book-list', 'my-loans', 'hostel-my-application', 'my-complaints',
             'applications-list', 'notices-list', 'ai-chat', 'my-id-card']

    def test_every_page_a_student_could_reach_before_is_still_linked(self):
        self.client.force_login(self.alice.user)
        html = self.client.get(reverse('student-dashboard')).content.decode()
        missing = [n for n in self.LINKS if f'href="{reverse(n)}"' not in html]
        self.assertEqual(missing, [])
        self.assertIn(f'href="{reverse("marksheet", args=[self.alice.pk])}"', html)

    def test_the_big_things_come_first_and_the_rest_is_collapsed(self):
        self.client.force_login(self.alice.user)
        html = self.client.get(reverse('student-dashboard')).content.decode()
        first_fold = html.index('<details class="fold"')
        for early in ("Today's Classes", 'Upcoming', 'Register courses', 'Attendance</span>'):
            self.assertLess(html.index(early), first_fold, early)        # visible before any collapsed section
        self.assertEqual(html.count('<details class="fold"'), html.count('</details>'))
        # only 4 headline numbers are shown up front
        self.assertEqual(html[:first_fold].count('class="stat-card'), 4)

    def test_attendance_section_opens_itself_only_when_a_subject_is_below_minimum(self):
        self.client.force_login(self.alice.user)
        calm = self.client.get(reverse('student-dashboard')).content.decode()
        self.assertNotIn('Attendance by Subject — Fall 2026\n    <span class="hint">1 subject', calm)
        for i, pres in enumerate((True, False, False)):
            AttendanceRecord.objects.create(student=self.alice, section=self.sec1, date=self.today - datetime.timedelta(days=i + 1),
                                            present=pres, semester=self.sem)
        html = self.client.get(reverse('student-dashboard')).content.decode()
        self.assertIn('<details class="fold" open>\n  <summary>✅ Attendance by Subject', html)
        self.assertIn('1 subject below 80%', html)

    def test_calm_message_when_nothing_needs_attention(self):
        self.client.force_login(self.bob.user)
        self.assertContains(self.client.get(reverse('student-dashboard')), 'Nothing needs your attention right now.')
