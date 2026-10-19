from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Sum, Count, Q
from django.db import transaction, IntegrityError
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from .forms import RegisterForm, NoticeForm, ProfileForm, SiteSettingsForm, AccountSettingsForm
from .models import Notice, Profile, SiteSettings
from .permissions import user_role, admin_required, role_required, staff_or_admin_required


def index(request):
    return render(request, 'core/index.html')


def _user_role(user):
    return user_role(user)


@login_required
def dashboard(request):
    """Routes each user to the dashboard that matches their role."""
    role = _user_role(request.user)
    if role == 'admin':
        return admin_dashboard(request)
    if role == 'faculty':
        return redirect('teacher-dashboard')
    if role == 'staff':
        return redirect('staff-dashboard')
    if role == 'guardian':
        return redirect('guardian-dashboard')
    return redirect('student-dashboard')


@admin_required
def admin_dashboard(request):
    from registration.models import Student
    from academics.models import Course, Program, CourseSection, CourseRegistration
    from attendance.models import AttendanceRecord
    from hr.models import Staff
    from finance.models import Invoice
    from complaints.models import Complaint
    from hostel.models import HostelApplication
    from admissions.models import Application
    from scholarships.models import ScholarshipApplication
    from exams.models import RetakeApplication

    stats = {
        'student_count': Student.objects.count(),
        'teacher_count': Staff.objects.count(),
        'program_count': Program.objects.count(),
        'course_count': Course.objects.count(),
        'section_count': CourseSection.objects.count(),
        'registration_count': CourseRegistration.objects.filter(status='registered').count(),
        'pending_invoices': Invoice.objects.filter(paid=False).count(),
        'open_complaints': Complaint.objects.filter(status__in=['open', 'in_progress']).count(),
        'pending_hostel': HostelApplication.objects.filter(status='pending').count(),
        'pending_admissions': Application.objects.filter(status='pending').count(),
    }
    from core.services.academic import AcademicEligibilityService
    _today_semester = AcademicEligibilityService.current_semester()
    if _today_semester:
        _today_records = AttendanceRecord.objects.filter(date=timezone.localdate(), semester=_today_semester)
        _today_total = _today_records.count()
        stats['todays_attendance_percent'] = round(_today_records.filter(present=True).count() * 100 / _today_total) if _today_total else None
    else:
        stats['todays_attendance_percent'] = None
    fee_collected = Invoice.objects.filter(paid=True).aggregate(total=Sum('amount'))['total'] or 0

    pending_approvals = [
        {'label': 'Hostel room assignments', 'count': HostelApplication.objects.filter(status='pending').count(), 'url': 'hostel-manage'},
        {'label': 'Scholarship applications', 'count': ScholarshipApplication.objects.filter(status='pending').count(), 'url': 'manage-scholarships'},
        {'label': 'Retake/improvement applications', 'count': RetakeApplication.objects.filter(status='pending').count(), 'url': 'manage-retake-applications'},
        {'label': 'Admission applications', 'count': Application.objects.filter(status='pending').count(), 'url': 'applications-list'},
    ]
    recent_applications = Application.objects.select_related('program', 'applicant').order_by('-applied_at')[:5]

    # The built-in local assistant is always available; external providers
    # are optional enhancements only.
    ai_configured = True

    # Live "Needs Attention" counts (Exception Center / Data Quality Center).
    # Computed fresh on every dashboard load - never cached/hard-coded.
    try:
        from oversight.services import OversightService
        needs_attention = OversightService.counts()
    except Exception:
        needs_attention = {'exceptions': 0, 'data_quality': 0}

    return render(request, 'core/admin-dashboard.html', {
        'stats': stats, 'fee_collected': fee_collected,
        'pending_approvals': pending_approvals, 'recent_applications': recent_applications,
        'ai_configured': ai_configured, 'needs_attention': needs_attention,
    })


@login_required
def document_center(request):
    """A single 'My Documents' hub linking to every official document the
    signed-in user can already generate elsewhere in the system (ID card,
    exam slip, marksheet, fee challans/receipts). This adds no new storage
    or generation - it reuses the existing, already permission-checked
    views for each document type, so there is no new place where access
    control could be gotten wrong. Admin/staff/faculty get a search box
    to look up a specific student's documents instead."""
    role = user_role(request.user)
    student = getattr(request.user, 'student_profile', None)

    context = {'role': role, 'is_own_documents': bool(student)}
    if student:
        from finance.models import Invoice
        context['student'] = student
        context['challans'] = Invoice.objects.filter(student=student).order_by('-created_at')[:20]
    elif role in ('admin', 'staff', 'faculty'):
        from registration.models import Student
        search = request.GET.get('q', '').strip()
        if search:
            from django.db.models import Q as _Q
            found = Student.objects.filter(
                _Q(full_name__icontains=search) | _Q(admission_no__icontains=search)
            ).select_related('program')[:20]
        else:
            found = Student.objects.none()
        context['search'] = search
        context['found_students'] = found

    return render(request, 'core/document-center.html', context)


@admin_required
def automation_center(request):
    """UI front-end for the same housekeeping the run_automation management
    command performs (fee-due reminders, overdue detection, low-attendance
    warnings) - so an admin doesn't need terminal/server access to run it.
    GET just shows the panel (plus real run history from the audit log);
    POST actually runs it."""
    from core.services.automation import AutomationService
    from .models import AuditLog
    result = None
    if request.method == 'POST':
        dry_run = request.POST.get('dry_run') == 'on'
        result = AutomationService.run(dry_run=dry_run)
        from core.models import log_action
        log_action(
            request.user, 'AUTOMATION_RUN', obj='dry run' if dry_run else 'live run',
            changes={k: ['', str(v)] for k, v in result.items()}, request=request,
        )
        if dry_run:
            messages.info(request, f"Dry run complete - no notifications sent. Would flag: {', '.join(f'{k}={v}' for k, v in result.items())}")
        else:
            messages.success(request, f"Automation run complete: {', '.join(f'{k}={v}' for k, v in result.items())}")

    # Real run history - covers both web-triggered runs and cron/systemd-timer
    # runs of `manage.py run_automation` (which logs the same action). No
    # fabricated "next run" time is shown here - only whatever actually ran,
    # since there's no live scheduler daemon running in every deployment.
    recent_runs = AuditLog.objects.filter(action='AUTOMATION_RUN').select_related('actor')[:10]
    last_run = recent_runs.first()
    from django.conf import settings as dj_settings
    from core import scheduler
    return render(request, 'core/automation-center.html', {
        'result': result, 'recent_runs': recent_runs, 'last_run': last_run,
        'scheduler_mode': scheduler.scheduler_mode(),
        'cron_enabled': len(getattr(dj_settings, 'CRON_SECRET', '')) >= 20,
        'jobs': scheduler.job_overview(),
    })


@admin_required
def audit_log(request):
    """Read-only view of sensitive-action history - admin only. The
    Django admin also exposes this (also read-only there), but this
    keeps it in the main UI rather than requiring a trip to /admin/."""
    from .models import AuditLog
    entries = AuditLog.objects.select_related('actor').all()
    action_filter = request.GET.get('action', '')
    if action_filter:
        entries = entries.filter(action=action_filter)
    actions = AuditLog.objects.order_by().values_list('action', flat=True).distinct()
    return render(request, 'core/audit-log.html', {
        'entries': entries[:200], 'actions': actions, 'action_filter': action_filter,
    })


@role_required('staff')
def staff_dashboard(request):
    """Operational queue for non-teaching (admin office) staff - the same
    pending-work items admin sees, without admin's site-configuration
    powers. Every linked page below is already reachable by the 'staff'
    role (staff_or_admin_required); this just gives staff a landing page
    that actually exists, instead of falling through to the student
    dashboard and getting a 403 because they have no Student record."""
    from finance.models import Invoice, Payment
    from complaints.models import Complaint
    from hostel.models import HostelApplication
    from admissions.models import Application
    from exams.models import RetakeApplication
    from django.utils import timezone

    context = {
        'pending_payments': Payment.objects.filter(status='pending').count(),
        'open_complaints': Complaint.objects.filter(status__in=['open', 'in_progress']).count(),
        'pending_hostel': HostelApplication.objects.filter(status='pending').count(),
        'pending_admissions': Application.objects.filter(status='pending').count(),
        'pending_retake_applications': RetakeApplication.objects.filter(status='pending').count(),
        'overdue_invoices': Invoice.objects.filter(paid=False, due_date__lt=timezone.localdate()).count(),
    }
    return render(request, 'core/staff-dashboard.html', {'stats': context})


@role_required('student')
def student_dashboard(request):
    context = {}
    from registration.models import Student as _Student
    if not _Student.objects.filter(user=request.user).exists():
        # Expected, explainable state (not a crash): the login exists but no student record is linked to it.
        messages.warning(request, 'No student record is linked to your account yet. Please contact the Registrar\'s office.')
        return render(request, 'core/student-dashboard.html', context)
    try:
        student = request.user.student_profile
        from finance.models import Invoice
        from library.models import BookLoan
        from hostel.models import HostelApplication, Hostel
        from attendance.models import AttendanceRecord
        from academics.models import CourseRegistration, CourseSection
        from exams.models import GradeEntry, RetakeApplication
        from core.models import Notice, Notification

        unpaid_qs = Invoice.objects.filter(student=student, paid=False).order_by('due_date')
        context['unpaid_invoices'] = unpaid_qs.count()
        context['academic_position'] = student.current_academic_position
        # Fee breakdown the student can act on directly from the dashboard,
        # instead of having to open Fees & Challans to discover something is
        # overdue - each row already carries its own category/amount/due date.
        context['unpaid_invoice_list'] = unpaid_qs[:5]
        context['overdue_invoice_count'] = sum(1 for inv in unpaid_qs if inv.is_overdue)

        context['active_loans'] = BookLoan.objects.filter(student=student, status='borrowed').count()

        hostel_status = HostelApplication.objects.filter(student=student).order_by('-applied_at').first()
        context['hostel_status'] = hostel_status
        # If the student never applied, show them whether a bed matching
        # their own gender is actually open right now, so "Apply for Hostel"
        # isn't a shot in the dark.
        if not hostel_status and student.gender:
            matching = Hostel.objects.filter(gender=student.gender, is_active=True)
            context['hostel_vacancy_available'] = any(
                h.total_capacity > h.total_occupied for h in matching
            )

        context['student'] = student
        from core.services.academic import AcademicEligibilityService
        current_semester = AcademicEligibilityService.current_semester()
        context['current_semester'] = current_semester

        # Attendance is scoped to the sections the student is registered in for
        # the current semester, with a per-course breakdown rather than one
        # blended percentage.
        attendance_by_course = []
        if current_semester:
            registered_sections = CourseSection.objects.filter(
                registrations__student=student, registrations__status='registered',
                registrations__semester=current_semester,
            ).select_related('course').distinct()
            semester_records = AttendanceRecord.objects.filter(
                student=student, section__in=registered_sections,
                date__gte=current_semester.start_date, date__lte=current_semester.end_date,
            )
            for section in registered_sections:
                sec_records = semester_records.filter(section=section)
                sec_total = sec_records.count()
                sec_present = sec_records.filter(present=True).count()
                attendance_by_course.append({
                    'course': section.course, 'section': section,
                    'present': sec_present, 'total': sec_total,
                    'pct': round((sec_present / sec_total) * 100, 1) if sec_total else None,
                })
            total = semester_records.count()
            present = semester_records.filter(present=True).count()
        else:
            total = present = 0
        context['attendance_by_course'] = attendance_by_course
        context['attendance_low_count'] = sum(1 for r in attendance_by_course if r['pct'] is not None and r['pct'] < 80)
        context['attendance_pct'] = round((present / total) * 100, 1) if total else None
        context['registered_courses'] = CourseRegistration.objects.filter(student=student, status='registered', semester=current_semester).count() if current_semester else 0

        from exams.models import canonical_grades
        # One row per (course, semester) - see canonical_grades(): without
        # this, a course that ended up with two exam-session rows (a real
        # data issue, not intended by the design) double-counted its
        # credits in CGPA and showed as two separate retake/improvement
        # opportunities instead of one.
        grades = canonical_grades(
            GradeEntry.objects.filter(student=student).select_related('exam__course')
        )
        total_points, total_credits = 0.0, 0
        for g in grades:
            credits = g.exam.course.credits or 0
            total_points += g.grade_point * credits
            total_credits += credits
        context['cgpa'] = round(total_points / total_credits, 2) if total_credits else None

        # Subjects the system already knows this student is eligible to
        # apply for improvement/retake on, and hasn't applied for yet -
        # surfaced automatically instead of making them dig through every
        # past result to notice a D or an F themselves.
        applied_grade_entry_ids = set(
            RetakeApplication.objects.filter(student=student)
            .exclude(status='rejected')
            .values_list('grade_entry_id', flat=True)
        )
        eligible_actions = []
        for g in grades:
            if g.id in applied_grade_entry_ids:
                continue
            if g.can_apply_retake:
                eligible_actions.append({'grade_entry': g, 'kind': 'Retake (Failed)'})
            elif g.can_apply_improvement:
                eligible_actions.append({'grade_entry': g, 'kind': 'Improvement (D grade)'})
        context['eligible_retake_actions'] = eligible_actions[:5]
        context['eligible_retake_count'] = len(eligible_actions)

        # Curriculum-driven recommendations: no manual semester assignment.
        from core.services.academic import AcademicEligibilityService
        context['recommended_courses'] = AcademicEligibilityService.recommended_courses(student, current_semester)[:8] if current_semester else []
        from core.services.academic import AcademicProgressService
        _progress = AcademicProgressService.calculate(student)
        context['academic_standing'] = _progress['standing']
        context['current_semester_gpa'] = _progress['current_semester_gpa']
        context['remaining_credits'] = _progress['remaining_credits']
        # Published dynamic assessment progress for the student's current registrations.
        from exams.services_dynamic import DynamicAssessmentService
        current_regs = CourseRegistration.objects.filter(student=student, status='registered', semester=current_semester).select_related('section__course') if current_semester else CourseRegistration.objects.none()
        assessment_progress = []
        for reg in current_regs:
            calc = DynamicAssessmentService.calculate(reg)
            pub = getattr(reg, 'result_publication', None)
            assessment_progress.append({'registration': reg, **calc,
                                        'published': bool(pub and pub.status == 'published'),
                                        'awaiting': bool(pub and pub.status not in ('published', 'reopened'))})
        context['assessment_progress'] = assessment_progress

        # Modules: today's classes, upcoming deadlines, degree progress, library.
        from core.services.student_dashboard import StudentDashboardService
        context['dash'] = StudentDashboardService.build(student, current_semester)

        context['recent_notices'] = Notice.objects.order_by('-published_at')[:3]

        # Unread in-app notifications (fee issued, hostel decided, grade
        # posted, complaint updated, ...) - the model already exists to
        # drive this, it just wasn't surfaced on the dashboard itself.
        unread = Notification.objects.filter(user=request.user, is_read=False)
        context['unread_notification_count'] = unread.count()
        context['recent_notifications'] = unread[:5]

        context['action_needed_count'] = (
            context['overdue_invoice_count']
            + context['eligible_retake_count']
            + (1 if (not hostel_status and context.get('hostel_vacancy_available')) else 0)
        )
    except Exception:
        import logging
        logging.getLogger('django.security').exception('Student dashboard failed to build context')
    return render(request, 'core/student-dashboard.html', context)


def _send_verification_email(request, user):
    """Send the verification email (6-digit code AND one-click link).
    Returns (verify_url, dev_code, error). dev_code is only set on a local
    developer machine with no mail server; it is never set in production."""
    from .otp_views import send_verification
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = request.build_absolute_uri(f"/verify-email/{uid}/{token}/")
    dev_code, ok, err = send_verification(request, user)
    if not ok and not err:
        err = ('We could not send the verification email right now. '
               'Use "Enter my code" and request a new code in a few minutes, or contact the administrator.')
    return verify_url, dev_code, err


def _using_console_email():
    """True only on a developer machine (DEBUG on) that has no mail server
    configured. Verification and reset codes are then shown on screen so local
    development works without email. This is NEVER true in production: showing
    a reset code to whoever typed an email address would let anyone take over
    that account."""
    return bool(settings.DEBUG) and settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend'


def register(request):
    site_settings_obj = SiteSettings.load()
    if not site_settings_obj.allow_public_registration:
        messages.error(request, 'New account registration is currently disabled. Please contact an administrator.')
        return redirect('login')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        account_role = request.POST.get('account_role', 'student')
        from .models import SiteSettings as _SS
        allowed_roles = ('student', 'faculty', 'staff') + (('guardian',) if _SS.load().enable_guardian_portal else ())
        if account_role not in allowed_roles:
            account_role = 'student'
        is_student = account_role == 'student'
        if is_student and form.is_valid() and not form.cleaned_data.get('program'):
            form.add_error('program', 'Please select your degree/program - this is required to register as a student.')
        if form.is_valid():
            role = account_role
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.is_active = False  # must verify email first
                    user.first_name = form.cleaned_data['full_name'].split(' ')[0]
                    user.save()
                    # update_or_create rather than create(): if a Profile row
                    # somehow already exists for this user (a retried/duplicate
                    # submission, a stale form resubmit, etc.) this updates it
                    # instead of crashing with an IntegrityError.
                    Profile.objects.update_or_create(user=user, defaults={'role': role})

                    if is_student:
                        from registration.models import Student
                        from core.services.academic import AcademicEligibilityService
                        import random
                        admission_no = f'UMS-{timezone.now().year}-{random.randint(10000, 99999)}'
                        while Student.objects.filter(admission_no=admission_no).exists():
                            admission_no = f'UMS-{timezone.now().year}-{random.randint(10000, 99999)}'
                        Student.objects.update_or_create(
                            user=user, defaults={
                                'full_name': form.cleaned_data['full_name'],
                                'cnic': form.cleaned_data['cnic'], 'admission_no': admission_no,
                                'program': form.cleaned_data.get('program'),
                                # Auto-assign the student's admission semester to
                                # whichever institutional semester is active right
                                # now, so their year/semester-of-study is available
                                # immediately (see Student.current_academic_position)
                                # without an admin having to set it by hand. Left
                                # unset (None) if no semester is currently active -
                                # an admin can fill it in later from Django admin.
                                'admission_semester': AcademicEligibilityService.current_semester(),
                            },
                        )
            except IntegrityError:
                messages.error(
                    request,
                    "That account couldn't be created because it already exists. "
                    "If you already registered, try logging in instead - or use "
                    "'Forgot password' if you don't remember your password.",
                )
                return redirect('register')
            except Exception:
                messages.error(
                    request,
                    "Something went wrong while creating your account. Please try again, "
                    "and contact an administrator if the problem continues.",
                )
                return redirect('register')

            verify_url, dev_code, err = _send_verification_email(request, user)
            request.session['pending_verify_user_id'] = user.pk
            context = {'email': user.email, 'error': err}
            if _using_console_email():
                context['dev_verify_url'] = verify_url
                context['dev_code'] = dev_code
            return render(request, 'core/verify-email-sent.html', context)
    else:
        form = RegisterForm()
    return render(request, 'core/register.html', {'form': form})


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save(update_fields=['is_active'])
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, 'Email verified! Welcome to UMS.')
        return redirect('dashboard')
    return render(request, 'core/verify-email-invalid.html')


@login_required
def profile(request):
    return render(request, 'core/profile.html')


@login_required
def edit_profile(request):
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    student = getattr(request.user, 'student_profile', None)
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile_obj)
        if form.is_valid():
            request.user.first_name = request.POST.get('first_name', '')
            request.user.last_name = request.POST.get('last_name', '')
            new_email = request.POST.get('email', '').strip()
            if new_email and new_email.lower() != request.user.email.lower():
                if User.objects.filter(email__iexact=new_email).exclude(pk=request.user.pk).exists():
                    messages.error(request, 'That email is already used by another account.')
                    return render(request, 'core/edit-profile.html', {'form': form})
                from . import otp
                from .otp_views import _console_email
                try:
                    code, _ok = otp.send_code_email(request.user, 'change_email',
                                                    request.build_absolute_uri('/account/confirm-email/'),
                                                    to_email=new_email, target_email=new_email.lower())
                    if _console_email():
                        request.session['dev_otp_code'] = code
                    messages.info(request, f'We sent a confirmation code to {new_email}. Enter it to finish changing your email.')
                    request.session['email_change_pending'] = True
                except otp.OTPError as e:
                    messages.error(request, str(e))
            request.user.save()
            form.save()
            if student:
                new_gender = form.cleaned_data.get('gender', '')
                if new_gender:
                    student.gender = new_gender
                    student.save(update_fields=['gender'])
                new_district = form.cleaned_data.get('district', '').strip()
                new_province = form.cleaned_data.get('province', '')
                if new_district or new_province:
                    if new_district:
                        student.district = new_district
                    if new_province:
                        student.province = new_province
                    student.save(update_fields=['district', 'province'])
                if not student.program and form.cleaned_data.get('program'):
                    student.program = form.cleaned_data['program']
                    student.save(update_fields=['program'])
                    messages.success(request, 'Profile updated - your program has been set.')
                    return redirect('change-email-confirm' if request.session.pop('email_change_pending', False) else 'profile')
            messages.success(request, 'Profile updated.')
            return redirect('change-email-confirm' if request.session.pop('email_change_pending', False) else 'profile')
    else:
        form = ProfileForm(instance=profile_obj, initial={
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'email': request.user.email,
            'gender': student.gender if student else '',
            'district': student.district if student else '',
            'province': student.province if student else '',
        })
    return render(request, 'core/edit-profile.html', {
        'form': form, 'is_student': bool(student),
        'needs_program': bool(student) and not student.program,
    })


@login_required
def notices_list(request):
    notices = Notice.objects.select_related('posted_by').all()
    return render(request, 'core/notices.html', {'notices': notices})


@staff_or_admin_required
def notice_add(request):
    if request.method == 'POST':
        form = NoticeForm(request.POST)
        if form.is_valid():
            notice = form.save(commit=False)
            notice.posted_by = request.user
            notice.save()
            from .models import notify_many
            notify_many(
                User.objects.filter(is_active=True).exclude(pk=request.user.pk),
                f'New notice: {notice.title}', notice.body[:150],
                level='info', url='/notices/',
            )
            messages.success(request, 'Notice published.')
            return redirect('notices-list')
    else:
        form = NoticeForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Notice', 'cancel_url': '/notices/'})


@admin_required
def reports(request):
    return render(request, 'core/reports.html')


@admin_required
def analytics(request):
    from decimal import Decimal
    from django.db.models import Count, Sum, Q
    from registration.models import Student
    from finance.models import Invoice
    from attendance.models import AttendanceRecord

    program_rows = list(
        Student.objects
        .values('program__name')
        .annotate(total=Count('id'))
        .order_by('-total', 'program__name')
    )
    max_program = max((row['total'] for row in program_rows), default=1)
    programs = [
        {
            'label': row['program__name'] or 'Unassigned',
            'total': row['total'],
            'percent': round((row['total'] / max_program) * 100, 1),
        }
        for row in program_rows
    ]

    paid_total = Invoice.objects.filter(paid=True).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    invoiced_total = Invoice.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    outstanding_total = max(Decimal('0'), invoiced_total - paid_total)
    fee_total = paid_total + outstanding_total
    paid_percent = round(float((paid_total / fee_total) * 100), 1) if fee_total else 0
    outstanding_percent = round(100 - paid_percent, 1) if fee_total else 0

    attendance_present = AttendanceRecord.objects.filter(present=True).count()
    attendance_absent = AttendanceRecord.objects.filter(present=False).count()
    attendance_total = attendance_present + attendance_absent
    attendance_present_percent = round((attendance_present / attendance_total) * 100, 1) if attendance_total else 0
    attendance_absent_percent = round(100 - attendance_present_percent, 1) if attendance_total else 0

    currency = getattr(SiteSettings.load(), 'currency_symbol', 'Rs.')
    context = {
        'programs': programs,
        'fees_paid_display': f'{currency} {paid_total:,.2f}',
        'fees_outstanding_display': f'{currency} {outstanding_total:,.2f}',
        'fees_paid_percent': paid_percent,
        'fees_outstanding_percent': outstanding_percent,
        'attendance_present': attendance_present,
        'attendance_absent': attendance_absent,
        'attendance_present_percent': attendance_present_percent,
        'attendance_absent_percent': attendance_absent_percent,
    }
    return render(request, 'core/analytics.html', context)


@admin_required
def report_student_count(request):
    from registration.models import Student
    data = Student.objects.values('program__name').annotate(total=Count('id')).order_by('-total')
    return render(request, 'core/report-student-count.html', {'rows': data})


@admin_required
def report_attendance(request):
    from attendance.models import AttendanceRecord
    total = AttendanceRecord.objects.count()
    present = AttendanceRecord.objects.filter(present=True).count()
    percentage = round((present / total) * 100, 1) if total else 0
    by_student = AttendanceRecord.objects.values('student__full_name').annotate(
        total=Count('id'), present=Count('id', filter=Q(present=True))
    ).order_by('student__full_name')
    return render(request, 'core/report-attendance.html', {
        'total': total, 'present': present, 'absent': total - present,
        'percentage': percentage, 'by_student': by_student,
    })


@admin_required
def report_fees(request):
    from finance.models import Invoice
    totals = Invoice.objects.aggregate(
        total_invoiced=Sum('amount'),
        total_count=Count('id'),
    )
    paid_total = Invoice.objects.filter(paid=True).aggregate(total=Sum('amount'))['total'] or 0
    outstanding = (totals['total_invoiced'] or 0) - paid_total
    return render(request, 'core/report-fees.html', {
        'total_invoiced': totals['total_invoiced'] or 0,
        'total_count': totals['total_count'] or 0,
        'paid_total': paid_total,
        'outstanding': outstanding,
    })


@login_required
def global_search(request):
    """Searches across students, teachers, courses, notices, and library
    books in one go - powers the sidebar search bar. Results are scoped by
    role: admin/office staff see everything; a faculty member only sees
    students actually enrolled in a section they teach (not the whole
    student body); a student never sees other students at all, only their
    own record if it matches - other people's private details (names,
    admission numbers) must never be searchable by a student."""
    query = request.GET.get('q', '').strip()
    results = {}
    if query:
        from registration.models import Student
        from hr.models import Staff
        from academics.models import Course
        from library.models import Book
        from core.permissions import user_role, section_scope_students

        role = user_role(request.user)

        student_matches = Student.objects.filter(
            Q(full_name__icontains=query) | Q(admission_no__icontains=query)
        )
        if role == 'student':
            # Only ever their own record, never another student's.
            student_matches = student_matches.filter(user=request.user)
        elif role in ('faculty', 'staff'):
            student_matches = section_scope_students(request.user, student_matches)
        results['students'] = student_matches[:10]

        results['teachers'] = Staff.objects.select_related('user').filter(
            Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) | Q(employee_id__icontains=query)
        )[:10]
        results['courses'] = Course.objects.filter(Q(name__icontains=query) | Q(code__icontains=query))[:10]
        results['notices'] = Notice.objects.filter(Q(title__icontains=query) | Q(body__icontains=query))[:10]
        results['books'] = Book.objects.filter(Q(title__icontains=query) | Q(author__icontains=query))[:10]
    return render(request, 'core/search-results.html', {'query': query, 'results': results})


class ThrottledLoginView(LoginView):
    """Login view with a simple per-username+IP attempt lockout, on top of
    Django's normal session/CSRF protections. Attempt limit and lockout
    duration are admin-configurable (Site Settings) rather than fixed in
    code, so a lockdown response never needs a redeploy."""
    template_name = 'core/login.html'

    def _limits(self):
        from .models import SiteSettings
        try:
            s = SiteSettings.load()
            return s.max_login_attempts, s.login_lockout_minutes * 60
        except Exception:
            return settings.LOGIN_THROTTLE_MAX_ATTEMPTS, settings.LOGIN_THROTTLE_WINDOW_SECONDS

    def _throttle_key(self):
        ip = self.request.META.get('REMOTE_ADDR', 'unknown')
        username = self.request.POST.get('username', '').lower()
        return f'login_throttle:{ip}:{username}'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            max_attempts, _window = self._limits()
            key = self._throttle_key()
            attempts = cache.get(key, 0)
            if attempts >= max_attempts:
                messages.error(request, 'Too many failed login attempts. Please wait a few minutes and try again.')
                return render(request, self.template_name, {'form': self.get_form_class()()})
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        _max_attempts, window = self._limits()
        key = self._throttle_key()
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, window)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._throttle_key())
        user = form.get_user()

        # Two-factor (fingerprint/face) check happens BEFORE the session is
        # established - opt-in for everyone by default, but an admin can
        # make it mandatory for admin accounts campus-wide (Site Settings).
        try:
            from .models import SiteSettings
            site_settings = SiteSettings.load()
            role_is_admin = user.is_staff or user.is_superuser
            must_2fa = user.profile.two_factor_enabled or (site_settings.require_2fa_for_admin and role_is_admin)
            if must_2fa and not user.webauthn_credentials.exists():
                if site_settings.require_2fa_for_admin and role_is_admin:
                    messages.error(
                        self.request,
                        'This account requires two-factor authentication, but no passkey is '
                        'registered yet. Contact another admin to register a device for you, or to temporarily '
                        'disable the "Require 2FA for admin" policy in Site Settings.',
                    )
                    return render(self.request, self.template_name, {'form': self.get_form_class()()})
                needs_2fa = False
            else:
                needs_2fa = must_2fa
        except Exception:
            needs_2fa = False
        if needs_2fa:
            self.request.session['pending_2fa_user_id'] = user.id
            return redirect('verify-2fa')

        response = super().form_valid(form)
        site_settings_obj = SiteSettings.load()
        if site_settings_obj.maintenance_mode and not (user.is_staff or user.is_superuser):
            from django.contrib.auth import logout
            logout(self.request)
            messages.error(self.request, site_settings_obj.maintenance_message or 'The site is temporarily down for maintenance.')
            return redirect('login')
        return response


from django.contrib.auth.views import PasswordResetView


from django.contrib.auth.forms import PasswordResetForm


class CodePasswordResetForm(PasswordResetForm):
    """Standard reset form, but the email also carries a 6-digit code so the
    user can either click the link or type the code on the site."""
    dev_code = None

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        from . import otp
        user = context['user']
        link = f"{context['protocol']}://{context['domain']}/password-reset/confirm/{context['uid']}/{context['token']}/"
        try:
            code, _ok = otp.send_code_email(user, 'password_reset', link, to_email=to_email)
            if _using_console_email():
                self.dev_code = code
        except otp.OTPError:
            pass  # rate limited: silently send nothing (also avoids revealing the account exists)


class DevAwarePasswordResetView(PasswordResetView):
    """Forgot-password: emails a code + link. When only the console mail
    backend is configured (development), the link/code are also shown on
    screen so nothing is hidden in a terminal window."""
    template_name = 'core/password_reset_form.html'
    form_class = CodePasswordResetForm

    def form_valid(self, form):
        response = super().form_valid(form)
        email = form.cleaned_data['email']
        self.request.session['reset_email'] = email
        if _using_console_email():
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                self.request.session['dev_reset_url'] = self.request.build_absolute_uri(f"/password-reset/confirm/{uid}/{token}/")
                if form.dev_code:
                    self.request.session['dev_otp_code'] = form.dev_code
        return response


from django.contrib.auth.views import PasswordResetDoneView
from django.views.decorators.http import require_POST


class DevAwarePasswordResetDoneView(PasswordResetDoneView):
    template_name = 'core/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dev_reset_url'] = self.request.session.pop('dev_reset_url', None)
        context['dev_code'] = self.request.session.get('dev_otp_code')
        return context


@admin_required
def site_settings(request):
    settings_obj = SiteSettings.load()
    if request.method == 'POST':
        form = SiteSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Settings updated.')
            return redirect('site-settings')
    else:
        form = SiteSettingsForm(instance=settings_obj)
    from core.checks import encryption_health_summary
    return render(request, 'core/settings.html', {'form': form, 'encryption_health': encryption_health_summary()})


@login_required
def account_settings(request):
    """Settings hub available to every role (student/teacher/admin) - profile
    shortcuts plus notification preferences. Site-wide config lives at
    /settings/ (admin only)."""
    profile_obj, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = AccountSettingsForm(request.POST, instance=profile_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notification preferences saved.')
            return redirect('account-settings')
    else:
        form = AccountSettingsForm(instance=profile_obj)

    # WebAuthn/passkeys are strictly tied to the exact browser origin
    # (scheme + hostname + port) - a passkey registered on
    # http://localhost:8000 will NOT work from http://127.0.0.1:8000, even
    # though both reach the same server. Detect that mismatch up front and
    # show a clear, actionable message instead of letting the person hit a
    # confusing "invalid domain" error from the browser itself when they
    # click Register Passkey.
    request_host = request.get_host().split(':')[0]
    webauthn_origin_mismatch = None
    if request_host != settings.WEBAUTHN_RP_ID:
        webauthn_origin_mismatch = (
            f"You're viewing this page as \"{request_host}\", but passkeys on this "
            f"installation are configured for \"{settings.WEBAUTHN_RP_ID}\". "
            f"Open the site at that address instead (e.g. "
            f"{settings.WEBAUTHN_ORIGIN}) before registering or using a passkey."
        )

    return render(request, 'core/account-settings.html', {
        'form': form, 'role': user_role(request.user),
        'profile_obj': profile_obj,
        'webauthn_devices': request.user.webauthn_credentials.all(),
        'webauthn_origin_mismatch': webauthn_origin_mismatch,
    })


@login_required
def notifications_list(request):
    """Full notification history for the signed-in user (own notifications only)."""
    from .models import Notification
    notes = Notification.objects.filter(user=request.user)
    return render(request, 'core/notifications.html', {'notifications': notes})


@login_required
@require_POST
def notification_read(request, pk):
    """Mark one notification read, then send the user to wherever it points."""
    from .models import Notification
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if not note.is_read:
        note.is_read = True
        note.save(update_fields=['is_read'])
    # Notification destinations are generated by the application. Refuse
    # absolute/external URLs anyway so a compromised/stale notification can
    # never become an open redirect.
    target = note.url or ''
    if not target.startswith('/') or target.startswith('//'):
        target = ''
    return redirect(target or 'notifications-list')


@login_required
@require_POST
def notifications_mark_all_read(request):
    from .models import Notification
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, 'All notifications marked as read.')
    return redirect(request.META.get('HTTP_REFERER') or 'notifications-list')


@admin_required
def automation_dashboard(request):
    from core.services.automation import AutomationService
    from core.models import Notification, SiteSettings
    from finance.models import Payment, Invoice
    from exams.models import RetakeApplication
    stats = AutomationService.run(dry_run=True)
    return render(request, 'core/automation-dashboard.html', {
        'stats': stats,
        'pending_payments': Payment.objects.filter(status='pending').count(),
        'pending_retake': RetakeApplication.objects.filter(status='pending').count(),
        'overdue_invoices': Invoice.objects.filter(paid=False, due_date__lt=timezone.localdate()).count(),
        'unread_notifications': Notification.objects.filter(is_read=False).count(),
        'settings_obj': SiteSettings.load(),
    })
