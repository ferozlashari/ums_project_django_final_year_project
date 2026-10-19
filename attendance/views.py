from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AttendanceRecord
from .forms import AttendanceForm
from core.permissions import staff_or_admin_required, user_role, section_scope_students, teaching_sections


@login_required
def attendance_list(request):
    records = AttendanceRecord.objects.select_related('student', 'section', 'section__course', 'student__program__department').all()
    role = user_role(request.user)
    today_record = None
    my_sections = []
    section_filter = request.GET.get('section', '').strip()
    if role == 'student':
        records = records.filter(student__user=request.user)
        try:
            student = request.user.student_profile
            today_record = AttendanceRecord.objects.filter(student=student, date=timezone.localdate()).first()
        except Exception:
            pass
    elif role in ('faculty', 'staff'):
        # Teachers only see attendance for students actually enrolled in a
        # section they teach - never the whole department, and never a
        # colleague's students, even within the same department.
        from registration.models import Student
        my_sections = teaching_sections(request.user).select_related('course')
        section_scoped_students = section_scope_students(request.user, Student.objects.all())
        records = records.filter(student__in=section_scoped_students)
        if section_filter:
            records = records.filter(section_id=section_filter)
    device_status = physical_biometric_status()
    device_options = [
        {'type': 'fingerprint', 'label': 'Fingerprint', 'icon': '🖐️', 'configured': bool(device_status.get('fingerprint'))},
        {'type': 'face', 'label': 'Face Recognition', 'icon': '📷', 'configured': bool(device_status.get('face'))},
        {'type': 'rfid', 'label': 'RFID Card', 'icon': '🪪', 'configured': bool(device_status.get('rfid'))},
    ]
    return render(request, 'core/attendance.html', {
        'attendance': records[:200], 'role': role, 'today_record': today_record,
        'my_sections': my_sections, 'section_filter': section_filter, 'device_options': device_options,
    })


@staff_or_admin_required
def attendance_add(request):
    role = user_role(request.user)
    if request.method == 'POST':
        form = AttendanceForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            if role in ('faculty', 'staff'):
                # Server-side enforcement, not just a narrowed dropdown -
                # a teacher can never record attendance for a section they
                # don't teach, even via a hand-crafted request.
                if record.section not in teaching_sections(request.user):
                    messages.error(request, "You can only record attendance for your own sections.")
                    return redirect('attendance-list')
            record.recorded_by = request.user
            record.method = 'manual'
            record.save()
            messages.success(request, 'Attendance recorded.')
            return redirect('attendance-list')
    else:
        form = AttendanceForm()

    if role in ('faculty', 'staff'):
        from registration.models import Student
        form.fields['section'].queryset = teaching_sections(request.user)
        form.fields['student'].queryset = section_scope_students(request.user, Student.objects.all())
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Record Attendance', 'cancel_url': '/attendance/'})


@staff_or_admin_required
def bulk_attendance(request):
    """Mark a whole section's attendance in one screen instead of one
    student at a time: pick a section + date, the actual registered
    roster loads automatically, tick who's absent (present is the
    default - matches how a teacher naturally works through a room), and
    save once. Idempotent - re-submitting the same section/date updates
    the existing records rather than creating duplicates, so this is
    safe to use to correct a day's attendance too."""
    role = user_role(request.user)
    from academics.models import CourseSection, Semester, CourseRegistration
    from core.services.academic import AcademicEligibilityService
    semester = AcademicEligibilityService.current_semester()
    if semester is None:
        messages.error(request, "No active semester is configured for today's date - an administrator must set the current semester before attendance can be taken.")
        return redirect('dashboard')
    sections = teaching_sections(request.user) if role in ('faculty', 'staff') else CourseSection.objects.select_related('course')
    section_id = request.GET.get('section') or request.POST.get('section', '')
    date_str = request.GET.get('date') or request.POST.get('date', '')
    # Validate the date rather than trusting a raw string, so a malformed value
    # never reaches the database and attendance cannot be marked for a future day
    # or a day outside the semester.
    import datetime as _dt
    try:
        parsed_date = _dt.date.fromisoformat(date_str) if date_str else timezone.localdate()
    except ValueError:
        messages.error(request, f'"{date_str}" is not a valid date - showing today instead.')
        parsed_date = timezone.localdate()
        date_str = ''
    selected_date = parsed_date.isoformat()
    date_problem = None
    if parsed_date > timezone.localdate():
        date_problem = 'Attendance cannot be recorded for a future date.'
    elif not (semester.start_date <= parsed_date <= semester.end_date):
        date_problem = f'{parsed_date:%d %b %Y} is outside {semester.display_name} ({semester.start_date:%d %b} - {semester.end_date:%d %b %Y}).'

    section = None
    roster = []
    existing_by_student = {}
    if section_id:
        section = sections.filter(pk=section_id).select_related('course').first()
        if section is None:
            messages.error(request, "You can only take attendance for your own sections.")
            return redirect('bulk-attendance')
        from academics.models import CourseRegistration
        registrations = list(
            CourseRegistration.objects.filter(section=section, status='registered', semester=semester)
            .select_related('student').order_by('student__full_name')
        )
        existing_by_student = {
            r.student_id: r.present for r in AttendanceRecord.objects.filter(section=section, date=selected_date, semester=semester)
        }
        # Precompute each row's checkbox default here rather than in the
        # template - Django templates have no dict-lookup-by-variable-key
        # filter built in, so this belongs in the view, not a made-up
        # template filter that would just fail silently.
        roster = [
            {'registration': reg, 'checked': existing_by_student.get(reg.student_id, True)}
            for reg in registrations
        ]

    if request.method == 'POST' and section and date_problem:
        messages.error(request, date_problem)
        return redirect(f"/attendance/bulk/?section={section.pk}&date={selected_date}")

    if request.method == 'POST' and section:
        from .services import save_section_attendance, AttendanceLocked
        present_ids = {row['registration'].student_id for row in roster
                       if f"present_{row['registration'].student_id}" in request.POST}
        try:
            saved = save_section_attendance(section, semester, parsed_date, present_ids, request.user,
                                            allow_locked=(role == 'admin'))
        except AttendanceLocked:
            messages.error(request, f'Attendance for {section} on {selected_date} has been finalised. Ask an administrator to reopen it.')
            return redirect(f"/attendance/bulk/?section={section.pk}&date={selected_date}")
        messages.success(request, f"Attendance saved for {saved} student(s) - {section} on {selected_date}.")
        return redirect(f"/attendance/bulk/?section={section.pk}&date={selected_date}")

    return render(request, 'core/bulk-attendance.html', {
        'sections': sections, 'section': section, 'selected_date': selected_date, 'roster': roster, 'date_problem': date_problem, 'max_date': timezone.localdate().isoformat(),
    })


@login_required
@require_POST
def self_checkin(request):
    """Smart Attendance: students mark themselves present for today with one
    tap - no teacher action needed. This is the software equivalent of a
    biometric/kiosk check-in terminal; it doesn't require special hardware,
    so it works on any phone or computer."""
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can self check-in.')
        return redirect('attendance-list')
    from core.models import SiteSettings
    if SiteSettings.load().require_biometric_attendance:
        messages.error(request, 'This campus requires biometric verification to check in - use the "Verify Identity" option instead.')
        return redirect('attendance-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('attendance-list')

    today = timezone.localdate()
    record, created = AttendanceRecord.objects.get_or_create(
        student=student, date=today,
        defaults={'present': True, 'method': 'self_checkin', 'check_in_time': timezone.now()},
    )
    if not created and not record.check_in_time:
        record.present = True
        record.method = 'self_checkin'
        record.check_in_time = timezone.now()
        record.save(update_fields=['present', 'method', 'check_in_time'])
        messages.success(request, f"Checked in at {record.check_in_time.strftime('%H:%M')}.")
    elif created:
        messages.success(request, f"Checked in at {record.check_in_time.strftime('%H:%M')}. Attendance marked automatically.")
    else:
        messages.info(request, 'Already checked in for today.')
    return redirect('attendance-list')


@login_required
@require_POST
def self_checkout(request):
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can self check-out.')
        return redirect('attendance-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('attendance-list')

    today = timezone.localdate()
    record = AttendanceRecord.objects.filter(student=student, date=today).first()
    if not record or not record.check_in_time:
        messages.error(request, 'Check in first before checking out.')
    elif record.check_out_time:
        messages.info(request, 'Already checked out for today.')
    else:
        record.check_out_time = timezone.now()
        record.save(update_fields=['check_out_time'])
        messages.success(request, f"Checked out at {record.check_out_time.strftime('%H:%M')}. Duration: {record.duration_display}.")
    return redirect('attendance-list')


def physical_biometric_status(campus=None):
    """Which physical biometric device types (fingerprint/face/RFID) are
    actually configured and enabled right now - for honest UI display.
    Returns a dict keyed by provider_type -> the enabled device, or None."""
    from biometrics.models import BiometricProviderConfig
    devices = BiometricProviderConfig.objects.filter(is_enabled=True)
    if campus:
        devices = devices.filter(campus=campus)
    by_type = {ptype: None for ptype, _ in BiometricProviderConfig.PROVIDER_CHOICES}
    for device in devices:
        by_type.setdefault(device.provider_type, device)
        if by_type[device.provider_type] is None:
            by_type[device.provider_type] = device
    return by_type


@login_required
@require_POST
def physical_biometric_checkin(request, provider_type):
    """Attendance via a REAL campus fingerprint/face/RFID device. Never
    fakes a verification: if no device of this type is configured and
    enabled, this refuses outright; if one is configured, it makes a real
    request to the device's own endpoint and records whatever it actually
    returns (verified / rejected / offline). An unreachable device is
    recorded as offline, never as a success."""
    from biometrics.models import BiometricProviderConfig, BiometricVerificationEvent
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can check in.')
        return redirect('attendance-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('attendance-list')

    device = BiometricProviderConfig.objects.filter(provider_type=provider_type, is_enabled=True).first()
    if not device:
        messages.error(request, f'No {dict(BiometricProviderConfig.PROVIDER_CHOICES).get(provider_type, provider_type)} device is configured for this campus yet - Status: Not Configured.')
        return redirect('attendance-list')

    result, reference = 'offline', ''
    if device.endpoint:
        try:
            import requests
            resp = requests.post(f'{device.endpoint.rstrip("/")}/verify', json={'student_reference': student.admission_no},
                                 timeout=float(device.config.get('timeout_seconds', 4)))
            resp.raise_for_status()
            data = resp.json()
            result = 'verified' if data.get('verified') else 'rejected'
            reference = data.get('reference', '')
        except Exception:
            result = 'offline'
    device.last_seen_at = timezone.now() if result != 'offline' else device.last_seen_at
    device.save(update_fields=['last_seen_at'])
    BiometricVerificationEvent.objects.create(provider=device, student=student, result=result,
                                              external_reference=reference, captured_at=timezone.now())

    if result != 'verified':
        label = {'rejected': 'was not recognised by the device', 'offline': 'device is offline or unreachable'}[result]
        messages.error(request, f'{device.get_provider_type_display()} check-in failed: {label}. Try again or use Self Check-In / Passkey.')
        return redirect('attendance-list')

    today = timezone.localdate()
    method = f'biometric_{provider_type}' if provider_type in ('fingerprint', 'face') else 'biometric_rfid'
    record, created = AttendanceRecord.objects.get_or_create(
        student=student, date=today, defaults={'present': True, 'method': method, 'check_in_time': timezone.now()},
    )
    if not created and not record.check_in_time:
        record.present, record.method, record.check_in_time = True, method, timezone.now()
        record.save(update_fields=['present', 'method', 'check_in_time'])
    messages.success(request, f'✅ {device.get_provider_type_display()} verified - checked in at {record.check_in_time.strftime("%H:%M") if record.check_in_time else "now"}.')
    return redirect('attendance-list')


@login_required
@require_POST
def biometric_checkin(request):
    """Check in for today using a verified passkey (WebAuthn) tap instead
    of a plain button - proves the phone/computer used really belongs to
    this student, not just anyone who knows their password."""
    from core.permissions import webauthn_recently_verified
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can check in.')
        return redirect('attendance-list')
    if not webauthn_recently_verified(request):
        messages.error(request, 'Passkey verification failed or expired - please try again.')
        return redirect('attendance-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('attendance-list')

    today = timezone.localdate()
    record, created = AttendanceRecord.objects.get_or_create(
        student=student, date=today,
        defaults={'present': True, 'method': 'biometric_webauthn', 'check_in_time': timezone.now()},
    )
    if not created and not record.check_in_time:
        record.present = True
        record.method = 'biometric_webauthn'
        record.check_in_time = timezone.now()
        record.save(update_fields=['present', 'method', 'check_in_time'])
    messages.success(request, f"✅ Biometrically verified and checked in at {record.check_in_time.strftime('%H:%M') if record.check_in_time else 'now'}.")
    return redirect('attendance-list')


# ---- correction requests ----------------------------------------------
@login_required
@require_POST
def correction_request(request, session_id):
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    from .models import AttendanceSession
    from .services import request_correction
    session = get_object_or_404(AttendanceSession.objects.select_related('section__course'), pk=session_id)
    if not teaching_sections(request.user).filter(pk=session.section_id).exists():
        raise PermissionDenied('You can only request corrections for your own sections.')
    try:
        request_correction(request.user, session, request.POST.get('reason', ''))
        messages.success(request, 'Correction request sent. You will be notified when it is decided.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(f"/teacher/attendance/today/?date={session.date.isoformat()}&all=1")


@login_required
def corrections_queue(request):
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import get_object_or_404
    from .models import AttendanceCorrectionRequest
    from .services import decide_correction, may_decide_corrections
    pending = AttendanceCorrectionRequest.objects.filter(status='pending').select_related(
        'session__section__course__program', 'requested_by')
    visible = [r for r in pending if may_decide_corrections(request.user, program=r.session.section.course.program)]
    if request.method == 'POST':
        req = get_object_or_404(AttendanceCorrectionRequest, pk=request.POST.get('req'))
        try:
            decide_correction(request.user, req, request.POST.get('decision') == 'approve', request.POST.get('note', ''))
            messages.success(request, f'Request {req.status}.')
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect('attendance-corrections')
    from core.permissions import user_role
    from governance.permissions import _current_assignments
    allowed = user_role(request.user) == 'admin' or any(
        a.role.permissions.filter(module='attendance', action='approve').exists()
        for a in _current_assignments(request.user))
    if not allowed:
        raise PermissionDenied('You do not have access to attendance corrections.')
    return render(request, 'core/attendance-corrections.html', {'requests': visible})
