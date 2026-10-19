"""Admission selection: merit ranking within seat limits.

Workflow: Application -> Entry test -> (pass = *eligible*, not admitted) ->
Merit ranking per seat pool -> Selected (accepted) / Waitlisted ->
Enrollment (Student record). Nothing is admitted merely for passing.
"""
import random
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from .models import Application, EntryTest, ProgramPreference
from core.models import SiteSettings


@dataclass
class SelectionResult:
    program: object
    accepted: list = field(default_factory=list)
    waitlisted: list = field(default_factory=list)
    enrolled: list = field(default_factory=list)


class AdmissionService:
    POOLS = {'open_merit': 'open_merit_seats', 'district_quota': 'district_quota_seats'}

    @staticmethod
    def merit_score(application):
        """Weighted merit out of 100: entry-test share + previous-percentage
        share, using the weight in Site Settings (100 = entry test only).
        A missing previous percentage counts as 0 for its share. Returns None
        until the entry test is evaluated."""
        from decimal import Decimal
        from core.models import SiteSettings
        test = getattr(application, 'entry_test', None)
        if test is None or test.marks_obtained is None:
            return None
        weight = Decimal(SiteSettings.load().merit_entry_test_weight)
        previous = application.previous_percentage or Decimal('0')
        return (test.marks_obtained * weight + previous * (Decimal('100') - weight)) / Decimal('100')

    @classmethod
    def eligible_queryset(cls, program, pool):
        """Passed the test, still undecided (pending) or already waitlisted."""
        apps = (Application.objects.filter(program=program, admission_type=pool, status__in=['pending', 'waitlist'],
                                           entry_test__marks_obtained__gt=EntryTest.PASS_MARK)
                .select_related('entry_test', 'applicant'))
        return sorted(apps, key=lambda a: (-cls.merit_score(a), a.applied_at, a.pk))

    @classmethod
    @transaction.atomic
    def select_for_program(cls, program, dry_run=False, enroll=True):
        """Rank eligible candidates per pool and fill only the seats that are
        still free. Re-running is safe (idempotent) and promotes waitlisted
        candidates automatically when seats open up."""
        result = SelectionResult(program=program)
        for pool, seat_field in cls.POOLS.items():
            total = getattr(program, seat_field) or 0
            taken = Application.objects.filter(program=program, admission_type=pool, status='accepted').count()
            free = max(0, total - taken)
            for index, app in enumerate(cls.eligible_queryset(program, pool)):
                if index < free:
                    result.accepted.append(app)
                    if not dry_run:
                        app.status = 'accepted'
                        app.remark = f'Selected on merit (rank {index + 1} in {app.get_admission_type_display()}).'
                        app.save(update_fields=['status', 'remark'])
                        if enroll and cls.enroll(app):
                            result.enrolled.append(app)
                else:
                    result.waitlisted.append(app)
                    if not dry_run and app.status != 'waitlist':
                        app.status = 'waitlist'
                        app.remark = f'Waitlisted - merit rank {index + 1} in {app.get_admission_type_display()}, {free} seat(s) available.'
                        app.save(update_fields=['status', 'remark'])
        return result

    @staticmethod
    def enroll(application):
        """Create the Student record for an accepted applicant that has a
        user account. Returns True if a new Student was created."""
        from registration.models import Student
        from core.models import notify
        if not application.applicant or Student.objects.filter(user=application.applicant).exists():
            return False
        year = timezone.now().year
        admission_no = f'UMS-{year}-{random.randint(10000, 99999)}'
        while Student.objects.filter(admission_no=admission_no).exists():
            admission_no = f'UMS-{year}-{random.randint(10000, 99999)}'
        from core.services.academic import AcademicEligibilityService
        # Student.save() creates the matching Enrollment automatically.
        student = Student.objects.create(
            user=application.applicant, full_name=application.display_name, cnic=application.cnic or '',
            admission_no=admission_no, program=application.program, status='active',
            admission_semester=AcademicEligibilityService.current_semester(),
        )
        # Program-wise admission fee challan, generated automatically for the
        # program the applicant actually WON (never a hard-coded amount).
        try:
            from finance.services import FeeChallanService
            FeeChallanService.generate_admission_fee(student)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Could not generate admission fee challan for application %s', application.pk)
        notify(application.applicant, 'Admission offer',
               'You have been selected on merit. Your student account is now active - check your dashboard.',
               level='success', url='/dashboard/')
        return True


@dataclass
class PreferenceAllocationResult:
    admission_type: str
    seated: dict = field(default_factory=dict)      # program_id -> [applications]
    unallocated: list = field(default_factory=list)


class PreferenceAllocationService:
    """Deferred-acceptance ("Gale-Shapley", applicant-proposing) allocation
    across up to 5 ranked program preferences, run separately per seat pool
    (open_merit / district_quota - each program's seats for that pool).

    Why deferred acceptance: a simpler "fill preference 1 first, then
    preference 2 with leftovers" approach can seat a lower-merit applicant
    in their 2nd choice while a higher-merit applicant who ALSO wanted that
    program is still waiting on their unresolved 1st choice - unstable and
    unfair. Deferred acceptance guarantees no such pair exists: every
    applicant ends up in the best program that would still take them,
    given everyone else's merit and preferences. It runs in at most 5
    rounds here (one per preference rank) and is fully deterministic.

    Algorithm, standard deferred acceptance:
      - Every applicant "proposes" to their top remaining unproposed
        preference.
      - Each program tentatively holds its top `seats` proposals (by merit
        score) among everyone who has ever proposed to it, rejecting the
        rest permanently for that program.
      - Rejected applicants propose to their next preference next round.
      - Repeat until no one has an unproposed preference left, or everyone
        is held somewhere.
    """

    @staticmethod
    def _seats_for(program, admission_type):
        """FREE seats in this program's pool: the configured seat count minus
        applicants already accepted into it (by an earlier run of this
        allocation, or by the single-program merit flow). Without this, a
        second run could seat a late applicant into an already-full program."""
        total = getattr(program, AdmissionService.POOLS[admission_type]) or 0
        taken = Application.objects.filter(program=program, admission_type=admission_type, status='accepted').count()
        return max(0, total - taken)

    @classmethod
    def run(cls, admission_type, dry_run=False):
        prefs_by_app = {}
        applications = {}
        for pref in (ProgramPreference.objects.filter(application__admission_type=admission_type,
                                                       application__status__in=['pending', 'waitlist'])
                     .select_related('application__entry_test', 'application', 'program').order_by('application_id', 'rank')):
            app = pref.application
            test = getattr(app, 'entry_test', None)
            if test is None or test.marks_obtained is None or test.marks_obtained <= EntryTest.PASS_MARK:
                continue  # not yet eligible - never proposed, never seated
            applications[app.pk] = app
            prefs_by_app.setdefault(app.pk, []).append(pref)

        next_index = {app_id: 0 for app_id in applications}
        held = {}          # app_id -> ProgramPreference currently held
        program_holders = {}  # program_id -> {app_id: ProgramPreference currently held}
        program_obj = {}      # program_id -> Program (kept separately: a full program may hold nobody)

        def merit(app_id):
            return AdmissionService.merit_score(applications[app_id])

        changed = True
        while changed:
            changed = False
            proposers = [aid for aid in applications if aid not in held and next_index[aid] < len(prefs_by_app[aid])]
            for aid in proposers:
                pref = prefs_by_app[aid][next_index[aid]]
                next_index[aid] += 1
                program_holders.setdefault(pref.program_id, {})[aid] = pref
                program_obj[pref.program_id] = pref.program
                changed = True
            for program_id, holders in program_holders.items():
                if not holders:
                    continue
                seats = cls._seats_for(program_obj[program_id], admission_type)
                ranked = sorted(holders.items(), key=lambda kv: (-merit(kv[0]), applications[kv[0]].applied_at, kv[0]))
                keep, drop = ranked[:seats], ranked[seats:]
                for aid, pref in keep:
                    held[aid] = pref
                for aid, pref in drop:
                    held.pop(aid, None)
                program_holders[program_id] = dict(keep)

        # Persist the outcome.
        buffer = SiteSettings.load().admission_waitlist_buffer
        result = PreferenceAllocationResult(admission_type=admission_type)

        # Every applicant's merit rank within EVERY program they listed, so
        # the applicant sees "Preference 1 - BSCS - Rank 12 - Selected".
        listed_by_program = {}
        for aid, prefs in prefs_by_app.items():
            for pref in prefs:
                listed_by_program.setdefault(pref.program_id, []).append(aid)
        rank_lookup = {}
        for program_id, aids in listed_by_program.items():
            ordered = sorted(aids, key=lambda x: (-merit(x), applications[x].applied_at, x))
            for position, aid in enumerate(ordered, start=1):
                rank_lookup[(aid, program_id)] = position

        with transaction.atomic():
            for aid, app in applications.items():
                prefs = prefs_by_app[aid]
                held_pref = held.get(aid)
                for i, pref in enumerate(prefs):
                    is_last = (i == len(prefs) - 1)
                    pref.merit_rank_in_program = rank_lookup[(aid, pref.program_id)]
                    if held_pref and pref.pk == held_pref.pk:
                        new_status = 'selected'
                    elif is_last and not held_pref:
                        seats = cls._seats_for(pref.program, admission_type)
                        new_status = 'waiting_list' if pref.merit_rank_in_program <= seats + buffer else 'not_allocated'
                    else:
                        new_status = 'not_allocated'
                    if not dry_run:
                        pref.status = new_status
                        pref.save(update_fields=['status', 'merit_rank_in_program'])
                if held_pref:
                    result.seated.setdefault(held_pref.program_id, []).append(app)
                    if not dry_run:
                        app.status = 'accepted'
                        app.program = held_pref.program      # keep the single-program field = the seat actually won
                        app.remark = f'Selected on merit - preference #{held_pref.rank} ({held_pref.program.code}).'
                        app.save(update_fields=['status', 'program', 'remark'])
                        AdmissionService.enroll(app)
                else:
                    result.unallocated.append(app)
                    if not dry_run:
                        app.status = 'waitlist' if any(p.status == 'waiting_list' for p in prefs) else 'rejected'
                        app.remark = 'Not allocated to any preferred program in this pool.'
                        app.save(update_fields=['status', 'remark'])
        return result
