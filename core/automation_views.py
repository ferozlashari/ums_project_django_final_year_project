"""Teacher / results-officer / student automation screens."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import role_required, user_role
from core.services.role_automation import (
    ResultWorkflowService, StudentAutomationService, TeacherAutomationService as T)

teacher_required = role_required('faculty')


def _int(v):
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return datetime.date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _day(request):
    raw = request.POST.get('date') or request.GET.get('date') or ''
    try:
        return datetime.date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError:
        messages.error(request, f'"{raw}" is not a valid date - showing today instead.')
        return timezone.localdate()


# ------------------------------------------------------------------ teacher
@teacher_required
def teacher_automation(request):
    if request.method == 'POST':
        dry = request.POST.get('dry_run') == 'on'
        stats = T.run_housekeeping(request.user, dry_run=dry)
        text = ', '.join(f'{k}={v}' for k, v in stats.items())
        (messages.info if dry else messages.success)(
            request, ('Dry run - nothing sent. Would notify: ' if dry else 'Housekeeping done: ') + text)
        return redirect('teacher-automation')
    today = timezone.localdate()
    semester, sheets = T.attendance_sheets(request.user, today)
    return render(request, 'core/teacher-automation.html', {
        'semester': semester, 'today': today,
        'todays_count': len(sheets), 'unmarked': [s for s in sheets if not s['already_marked']],
        'marks': T.marks_overview(request.user),
    })


@teacher_required
def teacher_attendance_today(request):
    day = _day(request)
    semester = T.current_semester()
    if semester is None:
        messages.error(request, 'No active semester is configured for today - an administrator must set it first.')
        return redirect('teacher-automation')
    from attendance.services import save_section_attendance, AttendanceLocked, date_problem
    show_all = request.GET.get('all') == '1' or request.POST.get('all') == '1'
    course_id = _int(request.GET.get('course') or request.POST.get('course'))
    problem = date_problem(semester, day)

    if request.method == 'POST':
        if problem:
            messages.error(request, problem)
            return redirect(f'{request.path}?date={day.isoformat()}')
        if request.POST.get('action') == 'present_all_unmarked':
            r = T.mark_all_present_where_unmarked(request.user, day)
            messages.success(request, f"Marked everyone present in {r['marked_sections']} class(es) "
                                      f"({r['marked_students']} students); {r['skipped_sections']} already had attendance.")
            return redirect(f'{request.path}?date={day.isoformat()}')
        _, sheets = T.attendance_sheets(request.user, day, show_all=show_all, course_id=course_id)
        lock = request.POST.get('finalise') == 'on'
        saved_total, locked_msgs = 0, []
        for sheet in sheets:
            sec = sheet['section']
            if f'include_{sec.pk}' not in request.POST:
                continue
            present = {r['student'].pk for r in sheet['rows'] if f"present_{sec.pk}_{r['student'].pk}" in request.POST}
            try:
                saved_total += save_section_attendance(sec, semester, day, present, request.user,
                                                       allow_locked=(user_role(request.user) == 'admin'), lock=lock)
            except AttendanceLocked:
                locked_msgs.append(str(sec))
        if saved_total:
            messages.success(request, f'Attendance saved for {saved_total} student record(s) on {day:%d %b %Y}.')
        for m in locked_msgs:
            messages.error(request, f'{m} is finalised and cannot be edited by a teacher.')
        return redirect(f'{request.path}?date={day.isoformat()}' + ('&all=1' if show_all else '') + (f'&course={course_id}' if course_id else ''))

    _, sheets = T.attendance_sheets(request.user, day, show_all=show_all, course_id=course_id)
    return render(request, 'core/teacher-attendance-today.html', {
        'sheets': sheets, 'day': day, 'problem': problem, 'show_all': show_all, 'semester': semester,
        'max_date': timezone.localdate().isoformat(), 'subjects': T.subjects_for(request.user), 'course_id': course_id,
        'total_students': sum(len(sh['rows']) for sh in sheets),
    })


@teacher_required
def teacher_marks(request, section_id):
    section = get_object_or_404(T.sections_for(request.user), pk=section_id)
    if request.method == 'POST':
        if request.POST.get('action') == 'submit':
            r = T.submit_complete_results(request.user, section)
            messages.success(request, f"Submitted {r['submitted']} complete result(s) for verification; "
                                      f"{r['incomplete']} incomplete, {r['already']} already submitted.")
        else:
            r = T.save_marks(request.user, section, request.POST)
            if r['saved']:
                messages.success(request, f"Saved {r['saved']} mark(s). Totals and grades are calculated automatically.")
            if r['locked']:
                messages.warning(request, f"{r['locked']} student(s) are already submitted - their marks are locked until an officer reopens them.")
            for e in r['errors'][:8]:
                messages.error(request, e)
        return redirect('teacher-marks', section_id=section.pk)
    return render(request, 'core/teacher-marks.html', {'section': section, 'sheet': T.marks_sheet(section)})


# ------------------------------------------------------------ results officer
@login_required
def results_workflow(request):
    from governance.permissions import has_perm
    if not (user_role(request.user) == 'admin' or _any_results_perm(request.user)):
        raise PermissionDenied('You do not have access to result verification.')
    if request.method == 'POST':
        from exams.models import ResultPublication
        pub = get_object_or_404(ResultPublication, pk=request.POST.get('pub'))
        try:
            if request.POST.get('action') == 'reopen':
                ResultWorkflowService.reopen(request.user, pub, request.POST.get('reason', ''))
                messages.success(request, 'Result reopened for the teacher. Reason recorded in the audit log.')
            else:
                new = ResultWorkflowService.advance(request.user, pub)
                messages.success(request, f'Result moved to: {new.replace("_", " ")}.')
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect('results-workflow')
    return render(request, 'core/results-workflow.html', {'items': ResultWorkflowService.queue(request.user)})


def _any_results_perm(user):
    from governance.permissions import _current_assignments
    return any(a.role.permissions.filter(module='results').exists() for a in _current_assignments(user))


# ------------------------------------------------------------------ student
@login_required
def student_automation(request):
    try:
        student = request.user.student_profile
    except Exception:
        raise PermissionDenied('Smart actions are available to students only.')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('register', 'all'):
            try:
                r = StudentAutomationService.register_recommended(student)
                if r['registered']:
                    messages.success(request, 'Registered: ' + ', '.join(str(s) for s in r['registered']))
                for s in r['skipped']:
                    messages.warning(request, f"{s['course'].code}: {s['reason']}")
                if not r['registered'] and not r['skipped']:
                    messages.info(request, 'Nothing left to register - you already have every recommended course.')
            except ValueError as exc:
                messages.error(request, str(exc))
        if action in ('challan', 'all'):
            res = StudentAutomationService.semester_challan(student)
            (messages.success if res.ok else messages.error)(request, res.message or f'Challan {res.invoice.challan_no} created.')
        return redirect('student-automation')
    return render(request, 'core/student-automation.html', {'o': StudentAutomationService.overview(student)})


# ------------------------------------------------- all classes at once
def _teachers_for_admin(user):
    if user_role(user) != 'admin':
        return []
    from hr.models import Staff
    return Staff.objects.filter(coursesection__isnull=False).select_related('user').distinct().order_by('user__first_name', 'employee_id')


@teacher_required
def teacher_attendance_summary(request):
    from academics.models import Semester
    g = request.GET
    semester = Semester.objects.filter(pk=_int(g.get('semester'))).first() or T.current_semester()
    data = T.attendance_summary(
        request.user, semester=semester, course_id=_int(g.get('course')), section_id=_int(g.get('section')),
        teacher_id=_int(g.get('teacher')) if user_role(request.user) == 'admin' else None,
        date_from=_date(g.get('from')), date_to=_date(g.get('to')), below_only=g.get('below') == '1', q=g.get('q', ''))
    return render(request, 'core/teacher-attendance-summary.html', {
        **data, 'subjects': T.subjects_for(request.user), 'sections': T.sections_for(request.user).order_by('course__code', 'code'),
        'semesters': Semester.objects.order_by('-start_date')[:12], 'teachers': _teachers_for_admin(request.user),
        'f': {'semester': semester.pk if semester else '', 'course': g.get('course', ''), 'section': g.get('section', ''),
              'teacher': g.get('teacher', ''), 'from': g.get('from', ''), 'to': g.get('to', ''),
              'below': g.get('below') == '1', 'q': g.get('q', '')},
    })


@teacher_required
def teacher_marks_all(request):
    g = request.GET
    course_id, section_id = _int(g.get('course')), _int(g.get('section'))
    teacher_id = _int(g.get('teacher')) if user_role(request.user) == 'admin' else None
    if request.method == 'POST':
        back = request.POST.get('qs', '')
        if request.POST.get('action') == 'submit':
            ids = [i for i in (_int(x) for x in request.POST.getlist('sections')) if i]
            r = T.submit_complete_results_all(request.user, ids)
            messages.success(request, f"Submitted {r['submitted']} complete result(s) for verification; "
                                      f"{r['incomplete']} incomplete, {r['already']} already submitted.")
        else:
            r = T.save_marks_all(request.user, request.POST)
            if r['saved']:
                messages.success(request, f"Saved {r['saved']} mark(s) across your classes. Totals and grades are calculated automatically.")
            if r['locked']:
                messages.warning(request, f"{r['locked']} student(s) are already submitted - their marks are locked until an officer reopens them.")
            for e in r['errors'][:8]:
                messages.error(request, e)
        return redirect(request.path + (f'?{back}' if back else ''))
    blocks, skipped = T.marks_blocks(request.user, course_id, section_id, teacher_id, g.get('status', ''), g.get('q', ''))
    return render(request, 'core/teacher-marks-all.html', {
        'blocks': blocks, 'skipped': skipped, 'subjects': T.subjects_for(request.user),
        'sections': T.sections_for(request.user).order_by('course__code', 'code'), 'teachers': _teachers_for_admin(request.user),
        'f': {'course': g.get('course', ''), 'section': g.get('section', ''), 'teacher': g.get('teacher', ''),
              'status': g.get('status', ''), 'q': g.get('q', '')},
        'qs': request.META.get('QUERY_STRING', ''),
        'student_count': sum(len(b['sheet']['rows']) for b in blocks),
    })
