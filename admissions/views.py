from decimal import Decimal
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from .models import Application, EntryTest, ProgramPreference
from registration.models import PROVINCE_CHOICES
from .forms import ApplicationForm, PublicApplicationForm, EntryTestScheduleForm, EntryTestResultForm, PreferencesForm
from core.permissions import user_role, admin_required, staff_or_admin_required
from core.models import notify




def _generate_roll_number():
    year = timezone.now().year
    while True:
        candidate = f'ET-{year}-{random.randint(10000, 99999)}'
        if not EntryTest.objects.filter(roll_number=candidate).exists():
            return candidate


@login_required
def apply(request):
    if user_role(request.user) in ('admin', 'faculty', 'staff'):
        messages.error(request, "Admission applications are for prospective/current students only - staff accounts don't apply.")
        return redirect('applications-list')

    from registration.models import Student
    # Already an enrolled student - admission is done, no point re-applying.
    existing_student = Student.objects.filter(user=request.user).first()
    if existing_student and existing_student.status in ('active', 'graduated'):
        messages.info(request, f"You're already {existing_student.get_status_display().lower()} in {existing_student.program} - no need to apply again. If you want to change programs, contact the admissions office directly.")
        return redirect('applications-list')

    # Already has an application in progress - don't let them submit a duplicate
    # while the first one is still pending/accepted/waitlisted.
    active_application = Application.objects.filter(
        applicant=request.user, status__in=['pending', 'accepted', 'waitlist'],
    ).select_related('program').first()
    if active_application:
        messages.info(
            request,
            f"You already have a {active_application.get_status_display().lower()} application for "
            f"{active_application.program.name} (submitted {active_application.applied_at:%b %d, %Y}). "
            "Only rejected applications can be re-submitted.",
        )
        return redirect('applications-list')

    if request.method == 'POST':
        form = ApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save_with_preferences(applicant=request.user)

            # Automatic entry test scheduling - the moment someone applies,
            # they get a test slip immediately, no admin action needed for
            # this step. Admin can still reschedule the date/venue later.
            entry_test = EntryTest.objects.create(
                application=app, roll_number=_generate_roll_number(),
                test_date=timezone.now().date() + timezone.timedelta(days=14),
            )
            notify(
                request.user, 'Admission entry test scheduled',
                f'Roll number {entry_test.roll_number} - {entry_test.test_date}. View your slip under Admissions.',
                level='info', url='/admissions/',
            )

            from finance.services import FeeChallanService
            from registration.models import Student
            student = Student.objects.filter(user=request.user).first()
            if student:
                result = FeeChallanService.generate_application_fee(student, app.program)
                fee_note = f' Application fee challan {result.invoice.challan_no} of {result.invoice.amount} generated.' if result.ok else ''
                messages.success(request, f'Application submitted with {app.preferences.count()} program choice(s). Entry test roll number: {entry_test.roll_number}.{fee_note}')
            else:
                messages.success(request, f'Application submitted with {app.preferences.count()} program choice(s). Entry test roll number: {entry_test.roll_number} - view your slip below. Fee challans are issued automatically once you are admitted.')
            return redirect('applications-list')
    else:
        form = ApplicationForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Apply for Admission', 'cancel_url': '/admissions/'})


def apply_public(request):
    """Public, no-login admissions form for prospective students."""
    from core.models import SiteSettings
    if request.user.is_authenticated:
        return redirect('apply')
    if not SiteSettings.load().allow_public_admissions:
        messages.error(request, 'Online admissions are currently closed. Please contact the admissions office.')
        return redirect('index')

    submitted = False
    roll_number = None
    if request.method == 'POST':
        form = PublicApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save_with_preferences()
            entry_test = EntryTest.objects.create(
                application=app, roll_number=_generate_roll_number(),
                test_date=timezone.now().date() + timezone.timedelta(days=14),
            )
            roll_number = entry_test.roll_number
            submitted = True
            form = PublicApplicationForm()
    else:
        form = PublicApplicationForm()
    return render(request, 'admissions/apply_public.html', {'form': form, 'submitted': submitted, 'roll_number': roll_number})


@login_required
def application_list(request):
    apps = Application.objects.select_related('program', 'applicant').all()
    role = user_role(request.user)
    if role not in ('admin', 'staff'):
        apps = apps.filter(applicant=request.user)

    context = {'role': role}
    if role in ('admin', 'staff'):
        district = request.GET.get('district', '').strip()
        province = request.GET.get('province', '').strip()
        program_id = request.GET.get('program', '').strip()
        status = request.GET.get('status', '').strip()
        if district:
            apps = apps.filter(district__icontains=district)
        if province:
            apps = apps.filter(province=province)
        if program_id:
            apps = apps.filter(program_id=program_id)
        if status:
            apps = apps.filter(status=status)
        from academics.models import Program
        context.update({
            'programs': Program.objects.all(), 'provinces': PROVINCE_CHOICES,
            'statuses': Application.STATUS_CHOICES,
            'filters': {'district': district, 'province': province, 'program': program_id, 'status': status},
        })
    context['applications'] = apps
    return render(request, 'core/applications.html', context)


@login_required
def seat_summary(request):
    """Per-program admission seat tracking - open merit vs district quota,
    filled (accepted applications) vs configured total. Admin/staff only."""
    role = user_role(request.user)
    if role not in ('admin', 'staff'):
        raise PermissionDenied('Only admin/staff can view the seat summary.')
    from academics.models import Program
    rows = []
    for program in Program.objects.select_related('department').all():
        open_merit_filled = Application.objects.filter(program=program, admission_type='open_merit', status='accepted').count()
        district_quota_filled = Application.objects.filter(program=program, admission_type='district_quota', status='accepted').count()
        rows.append({
            'program': program,
            'open_merit_filled': open_merit_filled, 'open_merit_total': program.open_merit_seats,
            'open_merit_remaining': max(0, program.open_merit_seats - open_merit_filled),
            'district_quota_filled': district_quota_filled, 'district_quota_total': program.district_quota_seats,
            'district_quota_remaining': max(0, program.district_quota_seats - district_quota_filled),
            'total_seats': program.open_merit_seats + program.district_quota_seats,
        })
    return render(request, 'core/seat-summary.html', {'rows': rows})


@login_required
def entry_test_slip(request, application_id=None):
    """Printable entry-test admit card. Students see only their own;
    admin can view any by application id."""
    if application_id is None:
        app = get_object_or_404(Application, applicant=request.user)
    else:
        app = get_object_or_404(Application, pk=application_id)
        if user_role(request.user) != 'admin' and app.applicant_id != request.user.id:
            raise PermissionDenied("You can only view your own entry test slip.")

    entry_test = getattr(app, 'entry_test', None)
    if entry_test is None:
        messages.error(request, 'No entry test has been scheduled for this application yet.')
        return redirect('applications-list')
    return render(request, 'admissions/entry-test-slip.html', {'application': app, 'entry_test': entry_test})


@admin_required
def entry_test_reschedule(request, pk):
    entry_test = get_object_or_404(EntryTest, pk=pk)
    if request.method == 'POST':
        form = EntryTestScheduleForm(request.POST, instance=entry_test)
        if form.is_valid():
            form.save()
            notify(
                entry_test.application.applicant, 'Entry test rescheduled',
                f'New date: {entry_test.test_date} at {entry_test.venue}.',
                level='warning', url='/admissions/',
            )
            messages.success(request, 'Entry test rescheduled.')
            return redirect('applications-list')
    else:
        form = EntryTestScheduleForm(instance=entry_test)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Reschedule — {entry_test.roll_number}', 'cancel_url': '/admissions/'})


@admin_required
def enter_entry_test_result(request, pk):
    """Entering the mark is the single decision point: pass automatically
    accepts the application AND creates the Student record in the same
    action; fail automatically rejects it. No separate manual
    'now enroll them' step - this is the automation the whole admission
    flow is built around."""
    entry_test = get_object_or_404(EntryTest, pk=pk)
    application = entry_test.application

    if request.method == 'POST':
        form = EntryTestResultForm(request.POST, instance=entry_test)
        if form.is_valid():
            entry_test = form.save(commit=False)
            entry_test.evaluated_at = timezone.now()
            entry_test.evaluated_by = request.user
            entry_test.save()

            if entry_test.passed:
                # Passing makes the candidate ELIGIBLE - it does not admit them.
                # Admission depends on merit rank versus the program's seats
                # (see AdmissionService.select_for_program).
                application.remark = 'Passed entry test - awaiting merit selection.'
                application.save(update_fields=['remark'])
                if application.applicant:
                    notify(
                        application.applicant, 'Entry test passed',
                        f'You scored {entry_test.marks_obtained}/100 (pass mark: {EntryTest.PASS_MARK}). '
                        'You are now eligible - final selection depends on merit rank and available seats.',
                        level='info', url='/admissions/',
                    )
                messages.success(request, f'Passed with {entry_test.marks_obtained}/100 - candidate is eligible. Run merit selection to fill seats.')
            else:
                application.status = 'rejected'
                application.save(update_fields=['status'])
                if application.applicant:
                    notify(
                        application.applicant, 'Admission entry test result',
                        f'You scored {entry_test.marks_obtained}/100 (pass mark: {EntryTest.PASS_MARK}). Unfortunately this does not meet the admission requirement.',
                        level='danger', url='/admissions/',
                    )
                messages.info(request, f'Scored {entry_test.marks_obtained}/100 - below pass mark, application rejected automatically.')
            return redirect('applications-list')
    else:
        form = EntryTestResultForm(instance=entry_test)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Enter Result — {entry_test.roll_number}', 'cancel_url': '/admissions/'})


@admin_required
def merit_list(request):
    """Rank every evaluated applicant per program by entry-test score,
    highest first - the actual 'fully on merit' admission mechanism.
    Doesn't change anyone's status by itself; it's a ranked view admin
    uses to decide cutoffs, since program capacity (not just the pass
    mark) often determines who's actually offered a seat."""
    from academics.models import Program

    program_id = request.GET.get('program', '').strip()
    programs = Program.objects.select_related('department').all()

    entries = EntryTest.objects.filter(marks_obtained__isnull=False).select_related(
        'application', 'application__program', 'application__applicant',
    ).order_by('application__program_id', '-marks_obtained')
    if program_id:
        entries = entries.filter(application__program_id=program_id)

    # Group into a per-program ranked list (rank computed here, in Python,
    # rather than a DB window function, to keep this portable across
    # SQLite/Postgres/MySQL without a raw-SQL dependency).
    grouped = {}
    for entry in entries:
        key = entry.application.program_id
        grouped.setdefault(key, {'program': entry.application.program, 'rows': []})
        rank = len(grouped[key]['rows']) + 1
        grouped[key]['rows'].append({'rank': rank, 'entry': entry})

    return render(request, 'admissions/merit-list.html', {
        'grouped': grouped.values(), 'programs': programs, 'selected_program': program_id,
    })


@admin_required
def run_selection(request):
    """Run merit selection for one program (POST). Ranks eligible candidates
    per seat pool, accepts up to the free seats, waitlists the rest and
    enrolls accepted applicants who have an account."""
    from django.views.decorators.http import require_POST  # noqa: F401
    from academics.models import Program
    from .services import AdmissionService
    if request.method != 'POST':
        return redirect('merit-list')
    program = get_object_or_404(Program, pk=request.POST.get('program'))
    result = AdmissionService.select_for_program(program, dry_run=bool(request.POST.get('dry_run')))
    mode = 'Preview' if request.POST.get('dry_run') else 'Selection complete'
    messages.success(request, f'{mode} for {program.name}: {len(result.accepted)} selected, {len(result.waitlisted)} waitlisted, {len(result.enrolled)} enrolled.')
    return redirect(f"/admissions/merit-list/?program={program.pk}")


@login_required
def application_preferences(request, pk):
    """The applicant's ranked program choices (up to 5) plus, once merit
    allocation has run, the result for each choice. Only the applicant (or
    staff) can open it; editing is only allowed while the application is
    still undecided."""
    application = get_object_or_404(Application.objects.select_related('program'), pk=pk)
    role = user_role(request.user)
    is_staff = role in ('admin', 'staff')
    if not is_staff and application.applicant_id != request.user.id:
        raise PermissionDenied('You can only view your own application.')

    editable = application.status == 'pending' and (not is_staff or request.user.is_superuser or role == 'admin')
    current = list(application.preferences.select_related('program').order_by('rank'))

    if request.method == 'POST':
        if not editable:
            messages.error(request, 'Preferences can no longer be changed - this application has already been decided.')
            return redirect('application-preferences', pk=pk)
        form = PreferencesForm(request.POST)
        if form.is_valid():
            programs = form.cleaned_data['ordered_programs']
            with transaction.atomic():
                application.preferences.all().delete()
                ProgramPreference.objects.bulk_create([
                    ProgramPreference(application=application, program=program, rank=rank)
                    for rank, program in enumerate(programs, start=1)
                ])
                application.program = programs[0]     # keep the single-program field = first choice
                application.save(update_fields=['program'])
            messages.success(request, f'Saved {len(programs)} program preference(s).')
            return redirect('application-preferences', pk=pk)
    else:
        initial = {f'preference_{p.rank}': p.program_id for p in current}
        if not initial and application.program_id:
            initial = {'preference_1': application.program_id}
        form = PreferencesForm(initial=initial)

    test = getattr(application, 'entry_test', None)
    from .services import AdmissionService
    return render(request, 'admissions/preferences.html', {
        'application': application, 'preferences': current, 'form': form, 'editable': editable,
        'merit_score': AdmissionService.merit_score(application), 'entry_test': test,
    })


@admin_required
def run_preference_allocation(request):
    """Run the ranked-preference merit allocation for one seat pool (POST).
    dry_run previews without saving or enrolling anyone."""
    from .services import PreferenceAllocationService
    if request.method != 'POST':
        return redirect('merit-list')
    admission_type = request.POST.get('admission_type', 'open_merit')
    if admission_type not in ('open_merit', 'district_quota'):
        messages.error(request, 'Unknown seat pool.')
        return redirect('merit-list')
    dry = bool(request.POST.get('dry_run'))
    result = PreferenceAllocationService.run(admission_type, dry_run=dry)
    seated = sum(len(v) for v in result.seated.values())
    label = 'Preview' if dry else 'Allocation complete'
    messages.success(request, f'{label} ({admission_type.replace("_", " ")}): {seated} applicant(s) seated, {len(result.unallocated)} not allocated.')
    return redirect('merit-list')
