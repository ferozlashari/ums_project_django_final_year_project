from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Staff, Payroll
from .forms import StaffForm, PayrollForm, PayrollPayForm
from core.permissions import admin_required, staff_or_admin_required, role_required
from governance.permissions import perm_required
from core.models import notify


@login_required
def hr_index(request):
    return render(request, 'core/notices.html', {'notices': []})


@admin_required
def teacher_list(request):
    query = request.GET.get('q', '').strip()
    teachers = Staff.objects.select_related('user', 'department').all()
    if query:
        teachers = teachers.filter(user__first_name__icontains=query) | teachers.filter(user__last_name__icontains=query) | teachers.filter(employee_id__icontains=query)
    return render(request, 'core/teacher-management.html', {'teachers': teachers, 'query': query})


@perm_required('hr', 'create')
def teacher_add(request):
    if request.method == 'POST':
        form = StaffForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Teacher added.')
            return redirect('teacher-list')
    else:
        form = StaffForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Teacher', 'cancel_url': '/hr/teachers/'})


@perm_required('hr', 'edit')
def teacher_edit(request, pk):
    staff = get_object_or_404(Staff, pk=pk)
    if request.method == 'POST':
        form = StaffForm(request.POST, instance=staff)
        if form.is_valid():
            form.save()
            messages.success(request, 'Teacher updated.')
            return redirect('teacher-list')
    else:
        form = StaffForm(instance=staff)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Teacher', 'cancel_url': '/hr/teachers/'})


@admin_required
@require_POST
def teacher_delete(request, pk):
    staff = get_object_or_404(Staff, pk=pk)
    staff.delete()
    messages.success(request, 'Teacher removed.')
    return redirect('teacher-list')


@role_required('faculty')
def teacher_dashboard(request):
    from academics.models import CourseSection, CourseRegistration
    from attendance.models import AttendanceRecord
    from exams.models import ExamSession, GradeEntry
    from django.utils import timezone
    import logging

    sections = []
    action_items = []
    student_count = 0
    dashboard_error = False
    try:
        staff = request.user.staff_profile
        sections = CourseSection.objects.filter(instructor=staff).select_related('course')
        today = timezone.localdate()

        section_ids = list(sections.values_list('id', flat=True))
        student_count = CourseRegistration.objects.filter(
            section_id__in=section_ids, status='registered',
        ).values('student_id').distinct().count()

        # Sections with no attendance recorded yet today - the thing a
        # teacher most needs a nudge about before the day is over.
        marked_today_section_ids = set(
            AttendanceRecord.objects.filter(section_id__in=section_ids, date=today)
            .values_list('section_id', flat=True)
        )
        for s in sections:
            if s.id not in marked_today_section_ids:
                action_items.append({
                    'label': f'Attendance not yet marked today — {s.course.code} (Section {s.code})',
                    'url': 'attendance-add',
                })

        # Exams for courses this teacher teaches, already held, still
        # missing grade entries for at least one registered student.
        taught_course_ids = sections.values_list('course_id', flat=True)
        past_exams = ExamSession.objects.filter(
            course_id__in=taught_course_ids, date__lte=today,
        ).select_related('course')
        for exam in past_exams:
            registered_count = CourseRegistration.objects.filter(
                section__course=exam.course, section_id__in=section_ids, status='registered',
            ).values('student_id').distinct().count()
            graded_count = GradeEntry.objects.filter(exam=exam).values('student_id').distinct().count()
            if registered_count and graded_count < registered_count:
                action_items.append({
                    'label': f'Grades pending — {exam} ({graded_count}/{registered_count} entered)',
                    'url': 'grade-add',
                })
        # classes timetabled today that still have no attendance saved.
        from core.services.role_automation import TeacherAutomationService as _TA
        _sem, _sheets = _TA.attendance_sheets(request.user, timezone.localdate())
        _todo = [sh for sh in _sheets if not sh['already_marked']]
        if _todo:
            action_items.append({'label': f"Attendance not taken yet today — {len(_todo)} class{'es' if len(_todo) != 1 else ''} "
                                          f"({', '.join(sh['section'].course.code for sh in _todo[:4])}{'…' if len(_todo) > 4 else ''})",
                                 'url': 'teacher-attendance-today'})
        # marks that need attention, from the same service the marks sheet uses.
        from core.services.role_automation import TeacherAutomationService as _T
        for m in _T.marks_overview(request.user):
            if m['scheme'] and m['students']:
                ready = m['complete'] - m['submitted']
                if ready > 0:
                    action_items.append({'label': f"{ready} complete result(s) ready to submit — {m['section'].course.code}", 'url': 'teacher-automation'})
                elif m['complete'] < m['students']:
                    action_items.append({'label': f"Marks incomplete — {m['section'].course.code} ({m['complete']}/{m['students']} students)", 'url': 'teacher-automation'})
    except Staff.DoesNotExist:
        # Expected/business case: a faculty-role account with no linked
        # Staff record yet. Not a bug - show a clear empty state, not an error.
        dashboard_error = False
    except Exception:
        # Unexpected/programming exception: never swallow this silently -
        # log it with a full traceback so it actually gets fixed, and tell
        # the teacher plainly that some data couldn't be loaded rather than
        # quietly showing an empty dashboard as if everything were fine.
        logging.getLogger('ums.errors').exception(
            'teacher_dashboard failed to compute sections/action items for user=%s', request.user
        )
        dashboard_error = True

    return render(request, 'core/teacher-dashboard.html', {
        'my_sections': sections,
        'action_items': action_items,
        'student_count': student_count,
        'dashboard_error': dashboard_error,
    })


@admin_required
def payroll_list(request):
    """Admin-only salary management - completely separate from student fee
    challans (Invoice model). Staff/faculty never pay fees; they get paid."""
    payslips = Payroll.objects.select_related('staff', 'staff__user').all()
    return render(request, 'core/payroll-list.html', {'payslips': payslips})


@admin_required
def payroll_add(request):
    if request.method == 'POST':
        form = PayrollForm(request.POST)
        if form.is_valid():
            payslip = form.save()
            messages.success(request, f'Payslip created for {payslip.staff.full_name} ({payslip.month:%b %Y}).')
            return redirect('payroll-list')
    else:
        form = PayrollForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Payslip', 'cancel_url': '/hr/payroll/'})


@admin_required
@require_POST
def payroll_generate_month(request):
    """One click - generate this month's payslip for every active staff
    member who has a monthly_salary set, skipping anyone who already has one."""
    today = timezone.localdate().replace(day=1)
    created = 0
    for staff in Staff.objects.exclude(monthly_salary__isnull=True):
        _, was_created = Payroll.objects.get_or_create(
            staff=staff, month=today, defaults={'amount': staff.monthly_salary},
        )
        if was_created:
            created += 1
    messages.success(request, f'Generated {created} payslip(s) for {today:%B %Y}.')
    return redirect('payroll-list')


@admin_required
@require_POST
def payroll_pay(request, pk):
    payslip = get_object_or_404(Payroll, pk=pk)
    if request.method == 'POST':
        form = PayrollPayForm(request.POST, instance=payslip)
        if form.is_valid():
            slip = form.save(commit=False)
            slip.status = 'paid'
            slip.paid_at = timezone.now()
            slip.paid_by = request.user
            slip.save()
            notify(
                slip.staff.user, f'Salary paid: {slip.month:%B %Y}',
                f'{slip.amount} has been paid.' + (f' Reference: {slip.reference}' if slip.reference else ''),
                level='success', url='/hr/payroll/',
            )
            messages.success(request, f'Marked paid for {slip.staff.full_name}.')
            return redirect('payroll-list')
    else:
        form = PayrollPayForm(instance=payslip)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Confirm Payment — {payslip.staff.full_name}', 'cancel_url': '/hr/payroll/'})


@role_required('faculty', 'staff')
def my_salary(request):
    """Read-only self-view: a teacher/staff member sees their own salary
    history, never anyone else's, and can't edit anything here - only
    admin can generate/confirm payslips (see payroll_list above)."""
    try:
        staff = request.user.staff_profile
    except Staff.DoesNotExist:
        messages.error(request, 'No staff record linked to this account.')
        return redirect('dashboard')
    payslips = Payroll.objects.filter(staff=staff)
    return render(request, 'core/my-salary.html', {'staff': staff, 'payslips': payslips})
