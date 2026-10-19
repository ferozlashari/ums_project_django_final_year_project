"""Tests: timetable planner, hostel/transport recommendations, weighted
merit, semester backfill and the student online-class empty state."""
import datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import (AcademicSession, Course, CourseRegistration, CourseSection, Department,
                              Faculty, Program, Semester)
from core.models import Profile, SiteSettings
from hr.models import Staff
from registration.models import Student
from timetable.models import Room, TimeSlot, TimetableAssignment
from timetable.services import TimetableService


class Base(TestCase):
    def setUp(self):
        today = timezone.localdate()
        faculty = Faculty.objects.create(name='Faculty')
        self.dept = Department.objects.create(name='CS', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=self.dept)
        session = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        self.sem = Semester.objects.create(name='Fall 2026', session=session, semester_number=1,
                                           start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90))

    def user(self, name, role='student', staff=False):
        u = User.objects.create_user(name, password='pw', is_staff=staff, is_superuser=(role == 'admin'))   # only a superuser is an admin
        Profile.objects.filter(user=u).update(role=role)
        return u

    def student(self, name, **kw):
        return Student.objects.create(user=self.user(name), full_name=name.title(), admission_no=f'A-{name}',
                                      program=self.program, status='active', **kw)

    def section(self, code, teacher=None, kind='lec', capacity=30):
        c = Course.objects.create(code=code, name=code, credits=3, program=self.program)
        return CourseSection.objects.create(course=c, code='A', instructor=teacher, capacity=capacity, section_type=kind)

    def register(self, student, section):
        return CourseRegistration.objects.create(student=student, section=section, semester=self.sem, status='registered')

    def teacher(self, name):
        return Staff.objects.create(user=self.user(name, role='faculty'), employee_id=f'E-{name}', department=self.dept)


class TimetableTests(Base):
    def setUp(self):
        super().setUp()
        self.t1, self.t2 = self.teacher('t1'), self.teacher('t2')
        self.room_big = Room.objects.create(name='Big', capacity=40)
        self.room_small = Room.objects.create(name='Small', capacity=2)
        self.lab = Room.objects.create(name='Lab1', capacity=40, room_type='lab')
        self.mon9 = TimeSlot.objects.create(day='mon', start_time=datetime.time(9), end_time=datetime.time(10))
        self.mon930 = TimeSlot.objects.create(day='mon', start_time=datetime.time(9, 30), end_time=datetime.time(10, 30))
        self.tue9 = TimeSlot.objects.create(day='tue', start_time=datetime.time(9), end_time=datetime.time(10))
        self.wed9 = TimeSlot.objects.create(day='wed', start_time=datetime.time(9), end_time=datetime.time(10))

    def test_detects_teacher_and_room_conflicts(self):
        a, b = self.section('C1', self.t1), self.section('C2', self.t1)
        TimetableAssignment.objects.create(section=a, room=self.room_big, timeslot=self.mon9, semester=self.sem)
        TimetableAssignment.objects.create(section=b, room=self.room_big, timeslot=self.mon930, semester=self.sem)
        kinds = {c['kind'] for c in TimetableService.conflicts(self.sem)}
        self.assertTrue({'teacher', 'room'} <= kinds)

    def test_detects_student_clash(self):
        a, b = self.section('C1', self.t1), self.section('C2', self.t2)
        s = self.student('stu')
        self.register(s, a); self.register(s, b)
        TimetableAssignment.objects.create(section=a, room=self.room_big, timeslot=self.mon9, semester=self.sem)
        TimetableAssignment.objects.create(section=b, room=self.lab, timeslot=self.mon930, semester=self.sem)
        self.assertIn('student', {c['kind'] for c in TimetableService.conflicts(self.sem)})

    def test_generated_draft_has_no_conflicts_and_respects_rooms(self):
        a, b = self.section('C1', self.t1), self.section('C2', self.t2)
        lab_sec = self.section('L1', self.t1, kind='lab')
        s = self.student('gen1')
        for sec in (a, b, lab_sec):
            self.register(s, sec)
        result = TimetableService.generate(self.sem)
        self.assertEqual(len(result['placed']), 3)
        self.assertEqual(TimetableService.conflicts(self.sem), [])
        placed = {p['section'].pk: p for p in result['placed']}
        self.assertEqual(placed[lab_sec.pk]['room'].room_type, 'lab')
        self.assertNotEqual(placed[a.pk]['room'].room_type, 'lab')
        self.assertTrue(all(t.status == 'draft' for t in TimetableAssignment.objects.all()))

    def test_room_capacity_is_respected(self):
        sec = self.section('C9', self.t1)
        for i in range(5):
            self.register(self.student(f'cap{i}'), sec)
        result = TimetableService.generate(self.sem)
        self.assertEqual(result['placed'][0]['room'].name, 'Big')      # 'Small' holds only 2

    def test_unplaceable_section_is_reported_not_forced(self):
        sec = self.section('C9', self.t1, capacity=500)
        for i in range(50):
            self.register(self.student(f'big{i}'), sec)
        result = TimetableService.generate(self.sem)
        self.assertEqual(result['unplaced'][0]['reason'], 'No suitable room is large enough.')
        self.assertEqual(TimetableAssignment.objects.count(), 0)

    def test_dry_run_saves_nothing_and_generate_is_idempotent(self):
        sec = self.section('C1', self.t1)
        self.register(self.student('dry'), sec)
        TimetableService.generate(self.sem, dry_run=True)
        self.assertEqual(TimetableAssignment.objects.count(), 0)
        TimetableService.generate(self.sem)
        TimetableService.generate(self.sem)
        self.assertEqual(TimetableAssignment.objects.count(), 1)

    def test_approval_blocked_by_conflicts_then_allowed(self):
        a, b = self.section('C1', self.t1), self.section('C2', self.t1)
        TimetableAssignment.objects.create(section=a, room=self.room_big, timeslot=self.mon9, semester=self.sem, status='draft')
        bad = TimetableAssignment.objects.create(section=b, room=self.lab, timeslot=self.mon930, semester=self.sem, status='draft')
        with self.assertRaises(ValueError):
            TimetableService.approve_drafts(self.sem)
        bad.timeslot = self.tue9
        bad.save()
        self.assertEqual(TimetableService.approve_drafts(self.sem), 2)

    def test_planner_is_admin_only_and_students_see_only_their_approved_sections(self):
        a, b = self.section('C1', self.t1), self.section('C2', self.t2)
        me = self.student('viewer')
        self.register(me, a)
        TimetableAssignment.objects.create(section=a, room=self.room_big, timeslot=self.mon9, semester=self.sem)
        TimetableAssignment.objects.create(section=b, room=self.lab, timeslot=self.tue9, semester=self.sem)
        self.client.force_login(me.user)
        self.assertNotEqual(self.client.get(reverse('timetable-planner')).status_code, 200)
        rows = list(self.client.get(reverse('timetable-list')).context['timetable'])
        self.assertEqual([r.section for r in rows], [a])
        self.client.force_login(self.user('boss', role='admin', staff=True))
        self.assertEqual(self.client.get(reverse('timetable-planner')).status_code, 200)


class HostelTests(Base):
    def setUp(self):
        super().setUp()
        from hostel.models import Hostel, Room as HRoom
        self.boys = Hostel.objects.create(name='Boys', gender='male')
        self.girls = Hostel.objects.create(name='Girls', gender='female')
        self.b_shared = HRoom.objects.create(hostel=self.boys, block='A', number='1', room_type='shared', capacity=2)
        self.g_shared = HRoom.objects.create(hostel=self.girls, block='G', number='1', room_type='shared', capacity=1)

    def app(self, name, gender, pref='shared'):
        from hostel.models import HostelApplication
        return HostelApplication.objects.create(student=self.student(name, gender=gender), room_type_preference=pref)

    def test_gender_matched_room_only(self):
        from hostel.services import HostelRecommendationService as S
        room, _ = S.recommend_room(self.app('m1', 'male'))
        self.assertEqual(room, self.b_shared)
        room, _ = S.recommend_room(self.app('f1', 'female'))
        self.assertEqual(room, self.g_shared)

    def test_full_room_is_never_suggested_and_beds_not_double_suggested(self):
        from hostel.services import HostelRecommendationService as S
        a, b = self.app('f2', 'female'), self.app('f3', 'female')     # girls' room has 1 bed
        results = {r[0].pk: r[1] for r in S.recommend_pending()}
        self.assertEqual(results[a.pk], self.g_shared)
        self.assertIsNone(results[b.pk])

    def test_missing_gender_gives_reason_not_a_guess(self):
        from hostel.services import HostelRecommendationService as S
        room, reason = S.recommend_room(self.app('nog', ''))
        self.assertIsNone(room)
        self.assertIn('gender', reason)

    def test_recommendation_does_not_approve_anything(self):
        from hostel.services import HostelRecommendationService as S
        app = self.app('m2', 'male')
        S.recommend_pending()
        app.refresh_from_db()
        self.assertEqual(app.status, 'pending')
        self.assertIsNone(app.assigned_room)
        self.assertEqual(app.recommended_room, self.b_shared)


class TransportTests(Base):
    def setUp(self):
        super().setUp()
        from transport.models import Vehicle, Route, RouteStop
        self.van = Vehicle.objects.create(registration_no='V-1', capacity=1)
        self.r1 = Route.objects.create(name='Hyderabad Road', vehicle=self.van, fare_per_semester=5000)
        self.stop1 = RouteStop.objects.create(route=self.r1, name='Latifabad Chowk', pickup_time=datetime.time(7), order=1)
        self.r2 = Route.objects.create(name='Jamshoro', fare_per_semester=3000)
        self.stop2 = RouteStop.objects.create(route=self.r2, name='Jamshoro Bridge', pickup_time=datetime.time(7, 30), order=1)

    def test_recommends_the_route_whose_stop_matches_the_address(self):
        from transport.services import TransportRecommendationService as S
        route, stop, _ = S.recommend(self.student('addr1', address='House 5, Latifabad Unit 8'))
        self.assertEqual((route, stop), (self.r1, self.stop1))

    def test_no_match_means_no_route_not_an_arbitrary_one(self):
        from transport.services import TransportRecommendationService as S
        route, stop, reason = S.recommend(self.student('far', address='Karachi Clifton'))
        self.assertIsNone(route)
        self.assertIn('No route stop matches', reason)

    def test_full_route_is_skipped(self):
        from transport.models import StudentTransportAssignment
        from transport.services import TransportRecommendationService as S
        StudentTransportAssignment.objects.create(student=self.student('rider', address='Latifabad'), route=self.r1, stop=self.stop1)
        route, _, _ = S.recommend(self.student('late', address='Latifabad'))
        self.assertIsNone(route)

    def test_assignment_requires_admin_click_and_admin_only(self):
        from transport.models import StudentTransportAssignment
        s = self.student('appr', address='Jamshoro')
        self.client.force_login(self.user('plain2'))
        self.client.post(reverse('transport-recommendations'), {'student': s.pk})
        self.assertFalse(StudentTransportAssignment.objects.exists())
        self.client.force_login(self.user('boss2', role='admin', staff=True))
        self.client.post(reverse('transport-recommendations'), {'student': s.pk})
        self.assertEqual(StudentTransportAssignment.objects.get(student=s).route, self.r2)


class WeightedMeritTests(Base):
    def make_app(self, name, marks, prev):
        from admissions.models import Application, EntryTest
        app = Application.objects.create(applicant=self.user(name), program=self.program, full_name=name, previous_percentage=prev)
        EntryTest.objects.create(application=app, roll_number=f'R{name}', test_date=datetime.date.today(), marks_obtained=marks)
        return app

    def test_default_weight_is_entry_test_only(self):
        from admissions.services import AdmissionService
        self.assertEqual(AdmissionService.merit_score(self.make_app('w1', 80, 50)), Decimal('80'))

    def test_weighted_merit_changes_the_ranking(self):
        from admissions.services import AdmissionService
        cfg = SiteSettings.load(); cfg.merit_entry_test_weight = 60; cfg.save()
        high_test = self.make_app('hi', 90, 40)     # 0.6*90 + 0.4*40 = 70
        balanced = self.make_app('bal', 80, 85)      # 0.6*80 + 0.4*85 = 82
        self.assertEqual(AdmissionService.merit_score(balanced), Decimal('82'))
        ranked = AdmissionService.eligible_queryset(self.program, 'open_merit')
        self.assertEqual([a.pk for a in ranked], [balanced.pk, high_test.pk])

    def test_missing_previous_percentage_counts_as_zero_for_its_share(self):
        from admissions.services import AdmissionService
        cfg = SiteSettings.load(); cfg.merit_entry_test_weight = 50; cfg.save()
        self.assertEqual(AdmissionService.merit_score(self.make_app('np', 80, None)), Decimal('40'))


class BackfillAndClassHintTests(Base):
    def test_backfill_dry_run_then_apply(self):
        sec = self.section('C1')
        stu = self.student('old')
        reg = CourseRegistration.objects.create(student=stu, section=sec, semester=None, status='registered')
        call_command('backfill_semesters', stdout=StringIO())
        reg.refresh_from_db()
        self.assertIsNone(reg.semester)                     # dry run changes nothing
        call_command('backfill_semesters', '--apply', stdout=StringIO())
        reg.refresh_from_db()
        self.assertEqual(reg.semester, self.sem)

    def test_student_with_no_registrations_is_told_why_the_list_is_empty(self):
        stu = self.student('lonely')
        self.client.force_login(stu.user)
        resp = self.client.get(reverse('class-list'))
        self.assertContains(resp, 'not registered in any course section')

    def test_registered_student_sees_live_class_and_unregistered_does_not(self):
        from onlineclass.models import OnlineClass
        teacher = self.teacher('host1')
        sec = self.section('C1', teacher)
        oc = OnlineClass.objects.create(title='Live one', section=sec, semester=self.sem, host=teacher,
                                        scheduled_at=timezone.now() - datetime.timedelta(minutes=5), duration_mins=60)
        mine, other = self.student('inclass'), self.student('outclass')
        self.register(mine, sec)
        self.client.force_login(mine.user)
        self.assertContains(self.client.get(reverse('class-list')), 'Live one')
        self.client.force_login(other.user)
        self.assertNotContains(self.client.get(reverse('class-list')), 'Live one')
