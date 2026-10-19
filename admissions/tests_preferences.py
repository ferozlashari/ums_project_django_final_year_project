"""Ranked-preference admissions: form rules, deferred-acceptance allocation
(bumping), per-preference rank/status, waiting list, pools, idempotency and
the applicant / admin views."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Department, Faculty, Program
from admissions.forms import PreferencesForm
from admissions.models import Application, EntryTest, ProgramPreference
from admissions.services import PreferenceAllocationService as Alloc
from core.models import Profile, SiteSettings
from registration.models import Student


class PrefBase(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        mk = lambda code, seats, quota=0: Program.objects.create(name=f'BS {code}', code=code, department=dept,
                                                                 open_merit_seats=seats, district_quota_seats=quota)
        self.A, self.B, self.C, self.D = mk('A', 1), mk('B', 1), mk('C', 1), mk('D', 1, quota=1)
        self.seq = 0

    def applicant(self, name, marks, programs, pool='open_merit'):
        self.seq += 1
        user = User.objects.create_user(name, password='pw')
        app = Application.objects.create(applicant=user, program=programs[0], admission_type=pool, full_name=name.title())
        EntryTest.objects.create(application=app, roll_number=f'R{self.seq}', test_date=datetime.date.today(), marks_obtained=marks)
        for rank, program in enumerate(programs, start=1):
            ProgramPreference.objects.create(application=app, program=program, rank=rank)
        return app

    def refresh(self, app):
        app.refresh_from_db()
        return app

    def pref(self, app, rank):
        return ProgramPreference.objects.get(application=app, rank=rank)


class AllocationTests(PrefBase):
    def setUp(self):
        super().setUp()
        # T(99) wants B; H(95) wants B then A; L(60) wants A then C.
        self.T = self.applicant('tara', 99, [self.B])
        self.H = self.applicant('hina', 95, [self.B, self.A])
        self.L = self.applicant('lala', 60, [self.A, self.C])

    def test_higher_merit_bumps_a_tentative_holder_who_then_moves_to_next_choice(self):
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(self.T).program, self.B)
        self.assertEqual(self.refresh(self.H).program, self.A)     # rejected by B, took A from L
        self.assertEqual(self.refresh(self.L).program, self.C)     # bumped from A, fell to choice 2
        for app in (self.T, self.H, self.L):
            self.assertEqual(self.refresh(app).status, 'accepted')

    def test_every_preference_gets_a_rank_and_the_right_status(self):
        Alloc.run('open_merit')
        self.assertEqual((self.pref(self.T, 1).status, self.pref(self.T, 1).merit_rank_in_program), ('selected', 1))
        self.assertEqual((self.pref(self.H, 1).status, self.pref(self.H, 1).merit_rank_in_program), ('not_allocated', 2))
        self.assertEqual((self.pref(self.H, 2).status, self.pref(self.H, 2).merit_rank_in_program), ('selected', 1))
        self.assertEqual((self.pref(self.L, 1).status, self.pref(self.L, 1).merit_rank_in_program), ('not_allocated', 2))
        self.assertEqual(self.pref(self.L, 2).status, 'selected')

    def test_student_is_enrolled_in_the_program_actually_won_not_the_first_choice(self):
        Alloc.run('open_merit')
        self.assertEqual(Student.objects.get(user=self.L.applicant).program, self.C)
        self.assertEqual(Student.objects.get(user=self.H.applicant).program, self.A)
        self.assertEqual(Student.objects.count(), 3)

    def test_running_twice_changes_nothing(self):
        Alloc.run('open_merit')
        Alloc.run('open_merit')
        self.assertEqual(Student.objects.count(), 3)
        self.assertEqual(self.refresh(self.L).program, self.C)

    def test_dry_run_saves_and_enrolls_nothing(self):
        result = Alloc.run('open_merit', dry_run=True)
        self.assertEqual(sum(len(v) for v in result.seated.values()), 3)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(self.refresh(self.L).status, 'pending')
        self.assertEqual(self.pref(self.L, 1).status, 'pending')

    def test_below_pass_mark_is_never_seated(self):
        weak = self.applicant('weak', 40, [self.C])
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(weak).status, 'pending')
        self.assertFalse(Student.objects.filter(user=weak.applicant).exists())

    def test_application_without_preference_rows_is_left_to_the_single_program_flow(self):
        user = User.objects.create_user('legacy', password='pw')
        legacy = Application.objects.create(applicant=user, program=self.C, full_name='Legacy')
        EntryTest.objects.create(application=legacy, roll_number='RLEG', test_date=datetime.date.today(), marks_obtained=88)
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(legacy).status, 'pending')


class WaitlistAndPoolTests(PrefBase):
    def test_last_choice_just_past_the_cutoff_is_waiting_list(self):
        winner = self.applicant('win', 90, [self.C])
        close = self.applicant('close', 80, [self.C])
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(winner).status, 'accepted')
        self.assertEqual(self.pref(close, 1).status, 'waiting_list')
        self.assertEqual(self.refresh(close).status, 'waitlist')

    def test_last_choice_far_past_the_cutoff_is_not_allocated_and_rejected(self):
        cfg = SiteSettings.load(); cfg.admission_waitlist_buffer = 0; cfg.save()
        self.applicant('win', 90, [self.C])
        far = self.applicant('far', 80, [self.C])
        Alloc.run('open_merit')
        self.assertEqual(self.pref(far, 1).status, 'not_allocated')
        self.assertEqual(self.refresh(far).status, 'rejected')

    def test_seats_already_taken_by_earlier_acceptances_are_respected_on_a_later_run(self):
        first = self.applicant('first', 90, [self.C])
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(first).status, 'accepted')
        late = self.applicant('late', 99, [self.C])          # higher merit, but arrives after the seat was given
        Alloc.run('open_merit')
        self.assertEqual(Application.objects.filter(program=self.C, status='accepted').count(), 1)
        self.assertNotEqual(self.refresh(late).status, 'accepted')

    def test_a_waitlisted_applicant_is_promoted_when_a_seat_is_freed(self):
        winner = self.applicant('win', 90, [self.C])
        close = self.applicant('close', 80, [self.C])
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(close).status, 'waitlist')
        Application.objects.filter(pk=winner.pk).update(status='rejected')     # winner declines the offer
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(close).status, 'accepted')

    def test_pools_are_independent(self):
        merit = self.applicant('mer', 70, [self.D], pool='open_merit')
        quota = self.applicant('quo', 60, [self.D], pool='district_quota')
        Alloc.run('open_merit')
        self.assertEqual(self.refresh(merit).status, 'accepted')
        self.assertEqual(self.refresh(quota).status, 'pending')        # different pool, not run yet
        Alloc.run('district_quota')
        self.assertEqual(self.refresh(quota).status, 'accepted')       # D has its own quota seat


class PreferencesFormTests(PrefBase):
    def data(self, **kw):
        return {f'preference_{n}': (kw.get(f'p{n}').pk if kw.get(f'p{n}') else '') for n in range(1, 6)}

    def test_first_choice_is_required(self):
        self.assertFalse(PreferencesForm(self.data()).is_valid())

    def test_duplicate_program_is_rejected(self):
        form = PreferencesForm(self.data(p1=self.A, p2=self.A))
        self.assertFalse(form.is_valid())
        self.assertIn('more than once', str(form.errors))

    def test_gap_in_choices_is_rejected(self):
        form = PreferencesForm(self.data(p1=self.A, p3=self.B))
        self.assertFalse(form.is_valid())
        self.assertIn('in order', str(form.errors))

    def test_five_distinct_choices_in_order_are_valid(self):
        E = Program.objects.create(name='BS E', code='E', department=self.A.department)
        form = PreferencesForm(self.data(p1=self.A, p2=self.B, p3=self.C, p4=self.D, p5=E))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual([p.code for p in form.cleaned_data['ordered_programs']], ['A', 'B', 'C', 'D', 'E'])


class PreferenceViewTests(PrefBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('viewer', password='pw')
        self.app = Application.objects.create(applicant=self.user, program=self.A, full_name='Viewer')
        self.url = reverse('application-preferences', args=[self.app.pk])

    def test_applicant_saves_ranked_choices_and_first_becomes_the_program(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {'preference_1': self.C.pk, 'preference_2': self.B.pk})
        self.assertEqual([(p.rank, p.program) for p in self.app.preferences.all()], [(1, self.C), (2, self.B)])
        self.assertEqual(self.refresh(self.app).program, self.C)

    def test_resubmitting_replaces_the_old_choices(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {'preference_1': self.A.pk, 'preference_2': self.B.pk})
        self.client.post(self.url, {'preference_1': self.D.pk})
        self.assertEqual(self.app.preferences.count(), 1)
        self.assertEqual(self.app.preferences.get().program, self.D)

    def test_another_user_cannot_open_it(self):
        self.client.force_login(User.objects.create_user('stranger', password='pw'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_choices_are_locked_once_the_application_is_decided(self):
        self.app.status = 'accepted'
        self.app.save()
        self.client.force_login(self.user)
        self.client.post(self.url, {'preference_1': self.B.pk})
        self.assertEqual(self.app.preferences.count(), 0)

    def test_result_is_shown_to_the_applicant_after_allocation(self):
        app = self.applicant('shown', 85, [self.B, self.C])
        Alloc.run('open_merit')
        self.client.force_login(app.applicant)
        resp = self.client.get(reverse('application-preferences', args=[app.pk]))
        self.assertContains(resp, 'Selected')
        self.assertContains(resp, 'Merit rank')

    def test_only_admins_can_run_the_allocation(self):
        app = self.applicant('runme', 85, [self.B])
        self.client.force_login(self.user)
        self.client.post(reverse('run-preference-allocation'), {'admission_type': 'open_merit'})
        self.assertEqual(self.refresh(app).status, 'pending')
        admin = User.objects.create_user('alloc_admin', password='pw', is_staff=True, is_superuser=True)
        Profile.objects.filter(user=admin).update(role='admin')
        self.client.force_login(admin)
        self.client.post(reverse('run-preference-allocation'), {'admission_type': 'open_merit'})
        self.assertEqual(self.refresh(app).status, 'accepted')
