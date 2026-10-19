from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST

from .models import ExamSession, GradeEntry, RetakeApplication, canonical_grades
from .forms import ExamForm, GradeEntryForm
from core.permissions import staff_or_admin_required, user_role, section_scope_students, teaching_sections
from core.models import notify, SiteSettings



@login_required
def exam_list(request):
    exams = ExamSession.objects.select_related('course', 'semester').all()
    role = user_role(request.user)
    verified_exam_ids = set()
    if role == 'student':
        from biometrics.models import ExamAttendance
        try:
            student = request.user.student_profile
            verified_exam_ids = set(ExamAttendance.objects.filter(student=student).values_list('exam_id', flat=True))
        except Exception:
            pass
    return render(request, 'core/exam-management.html', {
        'exams': exams, 'role': role, 'verified_exam_ids': verified_exam_ids,
    })


@staff_or_admin_required
def exam_add(request):
    if request.method == 'POST':
        form = ExamForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Exam added.')
            return redirect('exams')
    else:
        form = ExamForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Exam', 'cancel_url': '/exams/'})


@login_required
def results(request):
    grades = GradeEntry.objects.select_related('student', 'exam', 'exam__course', 'exam__semester', 'student__program__department').all()
    role = user_role(request.user)
    my_courses = []
    course_filter = request.GET.get('course', '').strip()
    # Students only see their own results.
    if role == 'student':
        grades = grades.filter(student__user=request.user)
    elif role in ('faculty', 'staff'):
        # Teachers only see results for students actually enrolled in a
        # section they teach - not the whole department.
        from registration.models import Student
        section_scoped_students = section_scope_students(request.user, Student.objects.all())
        grades = grades.filter(student__in=section_scoped_students)
        # ...and can narrow to one subject they teach ("subject-wise access").
        my_courses = teaching_sections(request.user).select_related('course').values_list(
            'course_id', 'course__code', 'course__name',
        ).distinct()
        if course_filter:
            grades = grades.filter(exam__course_id=course_filter)
    return render(request, 'core/results.html', {'results': grades, 'role': role, 'my_courses': my_courses, 'course_filter': course_filter})


def _scheme_course_redirect(request, course):
    """if administration defined an assessment scheme for this course, a TEACHER must grade it
    through the marks sheet (raw marks -> verify -> publish), not the legacy instant-grade form,
    which would bypass verification. Returns a redirect response, or None to carry on."""
    from exams.models import AssessmentScheme
    if not AssessmentScheme.objects.filter(course=course, is_active=True).exists():
        return None
    section = teaching_sections(request.user).filter(course=course).first()
    messages.error(request, f'{course.code} is graded through its assessment scheme. Use the marks sheet - '
                            'results go through verification before students see them.')
    return redirect('teacher-marks', section_id=section.pk) if section else redirect('teacher-automation')


@staff_or_admin_required
def grade_add(request):
    role = user_role(request.user)
    if request.method == 'POST':
        form = GradeEntryForm(request.POST)
        if form.is_valid():
            grade = form.save(commit=False)
            if role in ('faculty', 'staff'):
                # Server-side enforcement - a teacher can only grade exams
                # for courses they actually teach a section of.
                taught_course_ids = set(teaching_sections(request.user).values_list('course_id', flat=True))
                if grade.exam.course_id not in taught_course_ids:
                    messages.error(request, "You can only record grades for subjects you teach.")
                    return redirect('results')
                blocked = _scheme_course_redirect(request, grade.exam.course)
                if blocked:
                    return blocked
            if grade.attempt_type in ('retake', 'improvement'):
                error = _retake_attempt_entry_error(grade.student, grade.exam, grade.attempt_type)
                if error:
                    messages.error(request, error)
                    return redirect('results')
            grade.entered_by = request.user
            grade.save()
            notify(
                grade.student.user, f'New grade posted: {grade.exam.course.code}',
                f'Result for {grade.exam} is now available.',
                level='info', url='/exams/results/',
            )
            messages.success(request, 'Grade recorded.')
            return redirect('results')
    else:
        form = GradeEntryForm()

    if role in ('faculty', 'staff'):
        from registration.models import Student
        taught_course_ids = teaching_sections(request.user).values_list('course_id', flat=True)
        form.fields['exam'].queryset = ExamSession.objects.filter(course_id__in=taught_course_ids)
        form.fields['student'].queryset = section_scope_students(request.user, Student.objects.all())
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Record Grade', 'cancel_url': '/exams/results/'})


def _retake_attempt_entry_error(student, exam, attempt_type):
    """A retake/improvement grade may only be recorded once the student
    has an approved RetakeApplication with its challan paid for this exact
    course - otherwise a teacher could record a free re-attempt for a
    student who never applied or never paid. Returns an error string, or
    None if the entry is allowed."""
    application = RetakeApplication.objects.filter(
        student=student, application_type=attempt_type,
        grade_entry__exam__course=exam.course, status='approved',
    ).order_by('-applied_at').first()
    if not application:
        return f"{student.full_name} has no approved {attempt_type} application for {exam.course.code} - grades can't be recorded until they apply and it's approved."
    invoice = application.linked_invoice
    if invoice and not invoice.paid:
        return f"{student.full_name}'s {attempt_type} fee challan ({invoice.challan_no}) is unpaid - grades can't be recorded until it's paid."
    return None


@staff_or_admin_required
def grade_edit(request, pk):
    """Edit an existing grade entry - only reachable by admin, or by the
    teacher of that course while the automatic marks lock hasn't kicked in
    yet (see GradeEntry.is_locked). This is the actual enforcement point
    for the whole 'marks portal locks itself' automation - grade_add only
    ever creates new rows, this is the only place an existing one changes."""
    grade = get_object_or_404(GradeEntry, pk=pk)
    role = user_role(request.user)
    is_admin = role == 'admin'
    if role in ('faculty', 'staff'):
        from core.permissions import teaches_grade
        if not teaches_grade(request.user, grade):
            raise PermissionDenied('You can only edit grades for students in the sections you teach.')
        blocked = _scheme_course_redirect(request, grade.exam.course)
        if blocked:
            return blocked
    from governance.permissions import has_perm
    if grade.is_locked and not is_admin:
        messages.info(request, 'This result is locked. Submit a grade-correction request with a reason; an authorised officer will review it.')
        return redirect('grade-correction-request', pk=grade.pk)
    if grade.is_published and is_admin and not has_perm(request.user, 'results', 'override'):
        raise PermissionDenied('Editing a published result requires the results.override permission.')

    if request.method == 'POST':
        old_marks, old_grade = grade.marks, grade.grade  # captured before binding - is_valid() mutates form.instance in place
        old_components = {f: getattr(grade, f) for f in ('attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks')}
        form = GradeEntryForm(request.POST, instance=grade)
        if form.is_valid():
            from .models import ResultVersion
            ResultVersion.objects.create(
                grade_entry_id=grade.pk, marks=old_marks, grade=old_grade,
                components={k: (str(v) if v is not None else None) for k, v in old_components.items()},
                changed_by=request.user, reason='Edited via grade form')
            updated = form.save()
            from core.models import log_action
            log_action(
                request.user, 'GRADE_UPDATED', obj=f'{updated.student} / {updated.exam}',
                changes={'marks': [str(old_marks), str(updated.marks)], 'grade': [old_grade, updated.grade]},
                request=request,
            )
            messages.success(request, 'Grade updated.')
            return redirect('results')
    else:
        form = GradeEntryForm(instance=grade)
    if role in ('faculty', 'staff'):
        from registration.models import Student
        taught_course_ids = teaching_sections(request.user).values_list('course_id', flat=True)
        form.fields['exam'].queryset = ExamSession.objects.filter(course_id__in=taught_course_ids)
        form.fields['student'].queryset = section_scope_students(request.user, Student.objects.all())
    return render(request, 'core/form_base.html', {
        'form': form, 'title': f'Edit Grade - {grade.student} / {grade.exam}', 'cancel_url': '/exams/results/',
    })


@login_required
@require_POST
def grade_unlock(request, pk):
    """Admin-only override: reopen one locked grade entry for editing."""
    from governance.permissions import authority_perm
    if not authority_perm(request.user, 'results', 'override')[0]:
        raise PermissionDenied('Only the Controller of Examinations can unlock a marks entry.')
    grade = get_object_or_404(GradeEntry, pk=pk)
    grade.admin_unlocked = True
    grade.save(update_fields=['admin_unlocked'])
    from core.models import log_action
    log_action(request.user, 'GRADE_UNLOCKED', obj=f'{grade.student} / {grade.exam}', request=request)
    messages.success(request, f'Unlocked {grade.student} / {grade.exam} for editing.')
    return redirect('results')


@login_required
def result_checker(request):
    """Self-service result lookup: students see only their own; guardians
    see only their verified linked children; admin can look up anyone for
    management purposes. Deliberately NOT open to faculty/staff here - they
    already have a properly department-scoped view under Results; this
    quick admission-number lookup bypassed that scoping, so it's locked to
    the roles it's actually meant for."""
    from registration.models import Student
    from academics.models import Semester

    role = user_role(request.user)
    if role in ('faculty', 'staff'):
        raise PermissionDenied('Use the Results page for your own students - this quick lookup is for students, guardians, and admin only.')

    admission_no = request.GET.get('admission_no', '').strip()
    semester_id = request.GET.get('semester', '').strip()
    attempt_type = request.GET.get('attempt_type', '').strip()
    status_filter = request.GET.get('status', '').strip()

    allowed_admission_nos = None  # None = admin, unrestricted
    if role == 'student':
        try:
            admission_no = request.user.student_profile.admission_no
            allowed_admission_nos = {admission_no}
        except Exception:
            admission_no = ''
            allowed_admission_nos = set()
    elif role == 'guardian':
        from parents.models import GuardianLink
        allowed_admission_nos = set(
            GuardianLink.objects.filter(guardian=request.user, is_verified=True).values_list('student__admission_no', flat=True)
        )
        if not admission_no and len(allowed_admission_nos) == 1:
            admission_no = next(iter(allowed_admission_nos))

    student = None
    grades = []
    searched = bool(admission_no)
    if admission_no:
        if allowed_admission_nos is not None and admission_no not in allowed_admission_nos:
            raise PermissionDenied("You can only check results for your own verified children.")
        student = Student.objects.filter(admission_no__iexact=admission_no).select_related('program').first()
        if student:
            grades = GradeEntry.objects.filter(student=student).select_related('exam', 'exam__semester', 'exam__course')
            if semester_id:
                grades = grades.filter(exam__semester_id=semester_id)
            if attempt_type:
                grades = grades.filter(attempt_type=attempt_type)
            if status_filter:
                grades = [g for g in grades if g.status == status_filter]

    overall_status = None
    if grades:
        overall_status = 'fail' if any(g.status == 'fail' for g in grades) else 'pass'

    # Group by semester with a per-semester GPA, so the page reads like a
    # transcript instead of one flat table - and an overall CGPA/standing
    # so the student doesn't have to compute it themselves.
    # GPA/CGPA and retake/improvement counts must be one-per-course, not
    # one-per-exam-row - see canonical_grades(). The `grades` table above
    # still lists every exam attempt as-is (a student should be able to
    # see each one they sat), but a course that ended up with two exam-
    # session rows must not count its credits twice toward CGPA or show
    # up as two separate retake opportunities.
    gpa_grades = canonical_grades(grades) if grades else []

    semester_groups = []
    overall_points, overall_credits = 0.0, 0
    if student and gpa_grades:
        by_semester = {}
        order = []
        for g in gpa_grades:
            key = g.exam.semester_id
            if key not in by_semester:
                by_semester[key] = {'semester': g.exam.semester, 'grades': [], 'points': 0.0, 'credits': 0}
                order.append(key)
            entry = by_semester[key]
            entry['grades'].append(g)
            credits = g.exam.course.credits or 0
            entry['points'] += g.grade_point * credits
            entry['credits'] += credits
            overall_points += g.grade_point * credits
            overall_credits += credits
        for key in order:
            entry = by_semester[key]
            entry['gpa'] = round(entry['points'] / entry['credits'], 2) if entry['credits'] else None
            semester_groups.append(entry)
    cgpa = round(overall_points / overall_credits, 2) if overall_credits else None
    academic_standing = None
    if cgpa is not None:
        academic_standing = 'Good Standing' if cgpa >= 2.0 else 'Academic Warning'

    applied_grade_ids = set()
    if role == 'student' and student:
        applied_grade_ids = set(RetakeApplication.objects.filter(student=student).values_list('grade_entry_id', flat=True))

    retake_count = sum(1 for g in gpa_grades if g.can_apply_retake and g.id not in applied_grade_ids)
    improvement_count = sum(1 for g in gpa_grades if g.can_apply_improvement and g.id not in applied_grade_ids)

    return render(request, 'core/result-checker.html', {
        'admission_no': admission_no,
        'semesters': Semester.objects.select_related('session').order_by('-session__year', 'name'),
        'selected_semester': semester_id,
        'attempt_type': attempt_type, 'status_filter': status_filter,
        'student': student,
        'grades': grades,
        'overall_status': overall_status,
        'searched': searched,
        'role': role,
        'applied_grade_ids': applied_grade_ids,
        'semester_groups': semester_groups, 'cgpa': cgpa, 'academic_standing': academic_standing,
        'retake_count': retake_count, 'improvement_count': improvement_count,
    })


@login_required
def marksheet(request, student_id):
    """Printable marksheet for one student, grouped by semester."""
    from registration.models import Student

    student = get_object_or_404(Student, pk=student_id)
    role = user_role(request.user)
    from core.permissions import can_view_student
    if not can_view_student(request.user, student, module='results'):
        raise PermissionDenied("You can only view marksheets of students you are responsible for.")

    grades = GradeEntry.objects.filter(student=student).select_related('exam', 'exam__semester', 'exam__course').order_by('exam__semester__id', 'exam__course__code')
    by_semester = {}
    for g in grades:
        key = g.exam.semester.name if g.exam.semester else 'Unassigned'
        by_semester.setdefault(key, []).append(g)

    return render(request, 'core/marksheet.html', {'student': student, 'by_semester': by_semester})


@login_required
def apply_retake(request, grade_entry_id):
    """Student applies to retake a failed exam, or sit an improvement exam
    for one they already passed. GET shows a confirmation page with the
    course, previous grade/semester, fee and deadline before anything is
    created; POST actually submits it."""
    grade_entry = get_object_or_404(GradeEntry, pk=grade_entry_id)
    if user_role(request.user) != 'student' or grade_entry.student.user_id != request.user.id:
        raise PermissionDenied("You can only apply for your own exam retake/improvement.")

    existing = RetakeApplication.objects.filter(grade_entry=grade_entry).exclude(status='rejected').first()
    if existing:
        messages.info(request, 'You already have an application for this exam.')
        return redirect('my-retake-applications')

    if grade_entry.can_apply_retake:
        application_type = 'retake'
    elif grade_entry.can_apply_improvement:
        application_type = 'improvement'
    else:
        messages.error(request, f'Your grade ({grade_entry.letter_grade}) does not qualify for a retake or an improvement exam under the current grade scale.')
        return redirect('result-checker')

    site_settings = SiteSettings.load()
    max_attempts = site_settings.max_retake_attempts if application_type == 'retake' else site_settings.max_improvement_attempts
    prior_attempts = RetakeApplication.objects.filter(student=grade_entry.student, grade_entry__exam__course=grade_entry.exam.course, application_type=application_type).exclude(status='rejected').count()

    from django.utils import timezone
    window_years = site_settings.retake_window_years
    deadline = grade_entry.entered_at + timezone.timedelta(days=365 * window_years)
    fee = site_settings.retake_fee_amount if application_type == 'retake' else site_settings.improvement_fee_amount

    blocking_reasons = []
    if prior_attempts >= max_attempts:
        blocking_reasons.append('You have reached the configured maximum number of attempts for this course.')
    if timezone.now() > deadline:
        blocking_reasons.append(f'The {window_years}-year window to retake/improve this subject (from when the grade was recorded) has closed. Please contact administration.')
    # Exam registration window of the current semester. 'not_configured'
    # (no dates set by the administrator) does not block - it is only
    # enforced once dates are actually configured.
    from core.services.academic import AcademicEligibilityService
    _sem = AcademicEligibilityService.current_semester()
    if _sem is not None:
        _exam_state = _sem.exam_registration_state()
        if _exam_state == 'not_open':
            blocking_reasons.append(f'Exam registration for {_sem.display_name} opens on {timezone.localtime(_sem.exam_registration_open):%d %b %Y, %H:%M}.')
        elif _exam_state == 'closed':
            blocking_reasons.append(f'Exam registration for {_sem.display_name} closed on {timezone.localtime(_sem.exam_registration_close):%d %b %Y, %H:%M}.')

    if request.method == 'POST':
        if blocking_reasons:
            messages.error(request, ' '.join(blocking_reasons))
            return redirect('result-checker')
        RetakeApplication.objects.create(student=grade_entry.student, grade_entry=grade_entry, application_type=application_type)
        from finance.models import Invoice
        invoice = Invoice.objects.create(
            student=grade_entry.student, category='exam_retake', amount=fee,
            reference=f'{dict(RetakeApplication.APPLICATION_TYPE_CHOICES)[application_type]} - {grade_entry.exam.course.code}',
        )
        messages.success(request, f'{application_type.title()} application submitted for {grade_entry.exam.course.code}. Challan {invoice.challan_no} (Rs. {fee}) generated - pay it, then wait for staff approval to sit the exam.')
        return redirect('challan-detail', pk=invoice.pk)

    return render(request, 'core/apply-retake.html', {
        'grade_entry': grade_entry, 'application_type': application_type, 'fee': fee,
        'deadline': deadline, 'attempts_used': prior_attempts, 'max_attempts': max_attempts,
        'blocking_reasons': blocking_reasons,
    })


@login_required
def my_retake_applications(request):
    try:
        student = request.user.student_profile
        applications = RetakeApplication.objects.filter(student=student).select_related('grade_entry__exam__course')
    except Exception:
        applications = RetakeApplication.objects.none()
    return render(request, 'core/my-retake-applications.html', {'applications': applications})


@staff_or_admin_required
def manage_retake_applications(request):
    applications = RetakeApplication.objects.select_related('student', 'grade_entry__exam__course').order_by('-applied_at')
    return render(request, 'core/manage-retake-applications.html', {'applications': applications})


@staff_or_admin_required
@require_POST
def review_retake_application(request, pk):
    application = get_object_or_404(RetakeApplication, pk=pk)
    new_status = request.POST.get('status')
    if new_status in dict(RetakeApplication.STATUS_CHOICES):
        old_status = application.status
        application.status = new_status
        application.save(update_fields=['status'])
        from core.models import log_action
        log_action(
            request.user, 'RETAKE_APPLICATION_REVIEWED',
            obj=f'{application.student} / {application.grade_entry.exam} ({application.application_type})',
            changes={'status': [old_status, new_status]}, request=request,
        )
        notify(
            application.student.user, f'Retake application {application.get_status_display().lower()}',
            f'Your application for {application.grade_entry.exam} was {application.get_status_display().lower()}.',
            level='success' if new_status == 'approved' else 'warning',
            url='/exams/retake/my-applications/',
        )
        messages.success(request, f'Application marked {application.get_status_display()}.')
    return redirect('manage-retake-applications')


@login_required
def exam_slip(request, student_id=None):
    """Printable exam admit slip - one eligibility check per currently
    registered course (attendance in that specific section + no unpaid
    semester fee), not one blanket check for the whole student. A student
    can be on track in one course and short of attendance in another."""
    from registration.models import Student
    from attendance.models import AttendanceRecord
    from finance.models import Invoice
    from academics.models import CourseRegistration
    from core.services.academic import AcademicEligibilityService

    role = user_role(request.user)
    if student_id is None:
        student = Student.objects.filter(user=request.user).first()
        if student is None:
            messages.error(request, "There's no student record linked to your account, so there's no exam slip to show.")
            return redirect('dashboard')
    else:
        student = get_object_or_404(Student, pk=student_id)
        from core.permissions import can_view_student
        if not can_view_student(request.user, student, module='results'):
            raise PermissionDenied("You can only view exam slips of students you are responsible for.")

    min_attendance_percent = float(SiteSettings.load().minimum_attendance_percent)
    unpaid_semester_fee = Invoice.objects.filter(student=student, category='semester', paid=False).first()
    current_semester = AcademicEligibilityService.current_semester()

    course_status = []
    registrations = CourseRegistration.objects.filter(
        student=student, status='registered', semester=current_semester,
    ).select_related('section', 'section__course') if current_semester else []
    for reg in registrations:
        records = AttendanceRecord.objects.filter(student=student, section=reg.section)
        total = records.count()
        present = records.filter(present=True).count()
        pct = round((present / total) * 100, 1) if total else 0
        reasons = []
        if pct < min_attendance_percent:
            reasons.append(f'Attendance is {pct}% - minimum {min_attendance_percent}% required.')
        if unpaid_semester_fee:
            reasons.append(f'Outstanding semester fee challan {unpaid_semester_fee.challan_no} must be paid first.')
        course_status.append({
            'registration': reg, 'attendance_pct': pct,
            'eligible': not reasons, 'reasons': reasons,
        })

    # Overall attendance/eligibility, kept for the printable slip header
    # and for backward compatibility with anything still reading it.
    records = AttendanceRecord.objects.filter(student=student)
    total = records.count()
    present = records.filter(present=True).count()
    attendance_pct = round((present / total) * 100, 1) if total else 0
    eligible = bool(course_status) and all(c['eligible'] for c in course_status)
    reasons = [] if eligible else (
        ['No courses are registered for the current semester.'] if not course_status
        else ['Not every registered course meets the exam eligibility requirements below - see the course list.']
    )

    from academics.models import CourseRegistration as _CR
    _registered_courses = _CR.objects.filter(student=student, status='registered', section__course__program=student.active_program_id).values_list('section__course_id', flat=True)
    upcoming_exams = ExamSession.objects.filter(course_id__in=_registered_courses).order_by('date') if student.active_program_id else []

    return render(request, 'core/exam-slip.html', {
        'student': student, 'attendance_pct': attendance_pct, 'eligible': eligible,
        'reasons': reasons, 'unpaid_semester_fee': unpaid_semester_fee,
        'upcoming_exams': upcoming_exams, 'min_attendance_percent': min_attendance_percent,
        'course_status': course_status, 'current_semester': current_semester,
    })


@login_required
def gpa_calculator(request, student_id=None):
    """GPA per semester and overall CGPA, computed live from recorded
    grades (never stored/duplicated, so it's always in sync with results).
    Students see their own; staff/faculty/admin can look up any student."""
    from registration.models import Student
    role = user_role(request.user)
    if student_id is None:
        student = Student.objects.filter(user=request.user).first()
        if student is None:
            messages.error(request, "There's no student record linked to your account.")
            return redirect('dashboard')
    else:
        if role == 'student':
            raise PermissionDenied("You can only view your own GPA.")
        student = get_object_or_404(Student, pk=student_id)
        from core.permissions import can_view_student
        if not can_view_student(request.user, student, module='results'):
            raise PermissionDenied('You are not responsible for this student.')

    grades = canonical_grades(
        GradeEntry.objects.filter(student=student)
        .select_related('exam', 'exam__course', 'exam__semester')
        .order_by('exam__semester__semester_number', 'exam__course__code')
    )

    semesters = {}
    for g in grades:
        sem = g.exam.semester
        key = sem.pk if sem else 0
        label = sem.name if sem else 'Unassigned'
        bucket = semesters.setdefault(key, {'label': label, 'grades': [], 'points': 0.0, 'credits': 0})
        credits = g.exam.course.credits or 0
        bucket['grades'].append(g)
        bucket['points'] += g.grade_point * credits
        bucket['credits'] += credits

    semester_rows = []
    total_points, total_credits = 0.0, 0
    for key in sorted(semesters.keys()):
        b = semesters[key]
        gpa = round(b['points'] / b['credits'], 2) if b['credits'] else None
        semester_rows.append({'label': b['label'], 'grades': b['grades'], 'gpa': gpa, 'credits': b['credits']})
        total_points += b['points']
        total_credits += b['credits']

    cgpa = round(total_points / total_credits, 2) if total_credits else None

    return render(request, 'core/gpa-calculator.html', {
        'student': student, 'semester_rows': semester_rows, 'cgpa': cgpa, 'total_credits': total_credits,
    })


@login_required
def retake_slip(request, pk):
    """Printable admit slip for an approved retake/improvement exam -
    available once staff approves the application, not before."""
    application = get_object_or_404(RetakeApplication, pk=pk)
    if user_role(request.user) == 'student' and application.student.user_id != request.user.id:
        raise PermissionDenied("You can only view your own retake/improvement slip.")
    if application.status != 'approved':
        messages.error(request, 'This application has not been approved yet - no slip available.')
        return redirect('my-retake-applications')
    return render(request, 'core/retake-slip.html', {'application': application})


# ---------------------------------------------------------------------------
# Grade scale (admin-configured) and grade-correction workflow
# ---------------------------------------------------------------------------
def _grade_scale_rows(request):
    from decimal import Decimal, InvalidOperation
    rows, errors = [], []
    for i in range(0, 20):
        grade = request.POST.get(f'grade_{i}', '').strip()
        if not grade:
            continue
        try:
            rows.append({'grade': grade.upper()[:5], 'min_percent': Decimal(request.POST.get(f'min_{i}', '')),
                         'grade_point': Decimal(request.POST.get(f'gp_{i}', '')),
                         'is_pass': bool(request.POST.get(f'pass_{i}')),
                         'allows_improvement': bool(request.POST.get(f'improve_{i}'))})
        except (InvalidOperation, ValueError):
            errors.append(f'Row {grade}: percentage and grade point must be numbers.')
    return rows, errors


@login_required
def grade_scale(request):
    import datetime as _dt
    from decimal import Decimal
    from django.db import transaction
    from django.utils import timezone
    from governance.permissions import has_perm
    from .grading import bands_for, clear_cache, validate_bands
    from .models import GradeBand, GradeScale
    can_configure = has_perm(request.user, 'grade_policy', 'configure')
    if not (can_configure or has_perm(request.user, 'grade_policy', 'view') or user_role(request.user) in ('faculty', 'staff')):
        raise PermissionDenied('You do not have access to the grade scale.')
    if request.method == 'POST':
        if not can_configure:
            raise PermissionDenied('Only an administrator with grade_policy.configure can change the grade scale.')
        rows, errors = _grade_scale_rows(request)
        errors += validate_bands(rows) if rows else ['Enter at least two grades.']
        try:
            effective_from = _dt.datetime.strptime(request.POST.get('effective_from', ''), '%Y-%m-%d').date()
        except ValueError:
            effective_from = None
            errors.append('Choose a valid effective date.')
        if not errors:
            name = request.POST.get('name', '').strip() or f'Grade scale {timezone.localdate():%Y-%m-%d}'
            with transaction.atomic():
                for p in GradeScale.objects.filter(is_active=True, effective_until__isnull=True):
                    if p.effective_from < effective_from:
                        p.effective_until = effective_from - _dt.timedelta(days=1)
                        p.save(update_fields=['effective_until'])
                    else:
                        p.is_active = False
                        p.save(update_fields=['is_active'])
                scale = GradeScale.objects.create(name=name, effective_from=effective_from, created_by=request.user)
                ordered = sorted(rows, key=lambda r: r['min_percent'], reverse=True)
                for idx, r in enumerate(ordered):
                    upper = Decimal('100') if idx == 0 else ordered[idx - 1]['min_percent'] - Decimal('0.01')
                    GradeBand.objects.create(scale=scale, grade=r['grade'], min_percent=r['min_percent'], max_percent=upper,
                                             grade_point=r['grade_point'], is_pass=r['is_pass'],
                                             allows_improvement=r['allows_improvement'] and r['is_pass'])
            clear_cache()
            from core.models import log_action
            log_action(request.user, 'GRADE_SCALE_CHANGED', obj=scale.name,
                       changes={'effective_from': effective_from, 'grades': [f"{r['grade']}>={r['min_percent']}" for r in ordered]}, request=request)
            messages.success(request, 'New grade scale saved. Exams dated from the effective date use it; earlier exams keep the scale that applied then.')
            return redirect('grade-scale')
        for e in errors:
            messages.error(request, e)
    bands = bands_for()
    return render(request, 'core/grade-scale.html', {
        'rows': [{'i': i, 'b': b} for i, b in enumerate(bands)],
        'blank': list(range(len(bands), len(bands) + 3)), 'can_configure': can_configure,
        'today': timezone.localdate(), 'history': GradeScale.objects.all()[:10]})


@login_required
def grade_correction_request(request, pk):
    from decimal import Decimal, InvalidOperation
    from .models import ResultChangeRequest
    grade = get_object_or_404(GradeEntry, pk=pk)
    role = user_role(request.user)
    if role in ('faculty', 'staff'):
        from core.permissions import teaches_grade
        if not teaches_grade(request.user, grade):
            raise PermissionDenied('You can only request corrections for students in the sections you teach.')
    elif role != 'admin':
        raise PermissionDenied('Only the course teacher or an administrator can request a grade correction.')
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        proposed, errors = {}, []
        course = grade.exam.course
        caps = {'attendance_marks': course.attendance_weight, 'assignment_marks': course.assignment_weight,
                'midterm_marks': course.midterm_weight, 'final_marks': course.final_weight}
        for f, cap in caps.items():
            raw = request.POST.get(f, '').strip()
            if raw == '':
                continue
            try:
                v = Decimal(raw)
            except InvalidOperation:
                errors.append(f'{f.replace("_", " ").title()} must be a number.')
                continue
            if v < 0 or v > cap:
                errors.append(f'{f.replace("_", " ").title()} must be between 0 and {cap}.')
                continue
            proposed[f] = v
        if len(reason) < 10:
            errors.append('Give a clear reason (at least 10 characters).')
        if not proposed:
            errors.append('Enter at least one corrected component mark.')
        if ResultChangeRequest.objects.filter(grade_entry=grade, status='pending').exists():
            errors.append('A correction request for this result is already pending.')
        if not errors:
            ResultChangeRequest.objects.create(
                grade_entry=grade, requested_by=request.user, reason=reason,
                old_marks=grade.marks, old_grade=grade.letter_grade, **{'new_' + k: v for k, v in proposed.items()})
            from core.models import log_action
            log_action(request.user, 'RESULT_CORRECTION_REQUESTED', obj=f'{grade.student} / {grade.exam}',
                       changes={k: [str(getattr(grade, k)), str(v)] for k, v in proposed.items()}, reason=reason[:255], request=request)
            messages.success(request, 'Correction request submitted. The result stays unchanged until it is approved.')
            return redirect('grade-corrections')
        for e in errors:
            messages.error(request, e)
    return render(request, 'core/grade-correction-request.html', {'grade': grade, 'course': grade.exam.course})


@login_required
def grade_corrections(request):
    from governance.permissions import has_perm
    from .models import ResultChangeRequest
    qs = ResultChangeRequest.objects.select_related('grade_entry__student', 'grade_entry__exam__course', 'requested_by')
    can_review = has_perm(request.user, 'results', 'approve')
    if not can_review:
        if user_role(request.user) not in ('faculty', 'staff'):
            raise PermissionDenied('You do not have access to grade corrections.')
        qs = qs.filter(requested_by=request.user)
    return render(request, 'core/grade-corrections.html', {'requests': qs[:200], 'can_review': can_review})


@login_required
@require_POST
def grade_correction_decide(request, pk, decision):
    from django.db import transaction
    from django.utils import timezone
    from governance.permissions import authority_perm
    from .models import ResultChangeRequest, ResultVersion
    # Changing an already-verified result is the Controller of Examinations' decision (results.override).
    if not authority_perm(request.user, 'results', 'override')[0]:
        raise PermissionDenied('Only the Controller of Examinations can approve or reject grade corrections.')
    if decision not in ('approve', 'reject'):
        raise PermissionDenied('Unknown decision.')
    req = get_object_or_404(ResultChangeRequest, pk=pk)
    if req.status != 'pending':
        messages.info(request, 'This request was already decided.')
        return redirect('grade-corrections')
    if req.requested_by_id == request.user.id and not request.user.is_superuser:
        raise PermissionDenied('You cannot review your own correction request.')
    note = request.POST.get('note', '').strip()[:255]
    entry = req.grade_entry
    from core.models import log_action
    with transaction.atomic():
        if decision == 'approve':
            ResultVersion.objects.create(
                grade_entry=entry, marks=entry.marks, grade=entry.grade,
                components={f: (str(getattr(entry, f)) if getattr(entry, f) is not None else None) for f in req.COMPONENT_FIELDS},
                changed_by=request.user, reason=f'Correction request #{req.pk}: {req.reason}'[:255])
            before_marks, before_grade = entry.marks, entry.letter_grade
            for f, v in req.proposed_components().items():
                setattr(entry, f, v)
            entry.save()
            req.status = 'approved'
            log_action(request.user, 'RESULT_CORRECTED', obj=f'{entry.student} / {entry.exam}',
                       changes={'marks': [str(before_marks), str(entry.marks)], 'grade': [before_grade, entry.grade]},
                       reason=req.reason[:255], request=request)
        else:
            req.status = 'rejected'
            log_action(request.user, 'RESULT_CORRECTION_REJECTED', obj=f'{entry.student} / {entry.exam}', reason=note, request=request)
        req.reviewed_by = request.user
        req.reviewed_at = timezone.now()
        req.review_note = note
        req.save()
    messages.success(request, f'Correction {req.status}.')
    return redirect('grade-corrections')
