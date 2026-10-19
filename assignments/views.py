from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import Assignment, Submission
from .forms import AssignmentForm, SubmissionForm, GradeSubmissionForm
from django.core.exceptions import PermissionDenied
from core.permissions import can_manage_section, staff_or_admin_required, user_role
from core.models import notify


@login_required
def assignment_list(request):
    """Students see assignments only for sections they are actually
    registered in (not every section of every course in their program);
    teachers see assignments for sections they teach."""
    role = user_role(request.user)
    assignments = Assignment.objects.select_related('section', 'section__course').all()
    rows = []

    if role == 'student':
        try:
            student = request.user.student_profile
            from academics.models import CourseRegistration
            registered_section_ids = CourseRegistration.objects.filter(
                student=student, status='registered',
            ).values_list('section_id', flat=True)
            assignments = assignments.filter(section_id__in=registered_section_ids)
            submissions_by_assignment = {
                s.assignment_id: s for s in Submission.objects.filter(student=student)
            }
        except Exception:
            assignments = Assignment.objects.none()
            submissions_by_assignment = {}
        # Pair each assignment with the student's own submission (or None) -
        # done here in Python so the template never needs a dict-by-key
        # lookup filter that Django doesn't provide out of the box.
        for a in assignments:
            rows.append({'assignment': a, 'submission': submissions_by_assignment.get(a.id)})
    else:
        if role in ('faculty', 'staff'):
            try:
                assignments = assignments.filter(section__instructor=request.user.staff_profile)
            except Exception:
                pass
        for a in assignments:
            rows.append({'assignment': a, 'submission': None})

    return render(request, 'assignments/list.html', {'rows': rows, 'role': role})


@staff_or_admin_required
def assignment_add(request):
    if request.method == 'POST':
        form = AssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.created_by = request.user
            assignment.save()

            from registration.models import Student
            from academics.models import CourseRegistration
            from core.models import notify_many
            # Only notify/show this to students actually registered in
            # THIS section, not everyone in the program (see
            # assignment_list docstring above for the same fix).
            registered_student_ids = CourseRegistration.objects.filter(
                section=assignment.section, status='registered',
            ).values_list('student_id', flat=True)
            students = Student.objects.filter(id__in=registered_student_ids)
            notify_many(
                [s.user for s in students], f'New assignment: {assignment.title}',
                f'{assignment.section.course.code} - due {assignment.due_date:%b %d, %H:%M}',
                level='info', url='/assignments/',
            )
            messages.success(request, 'Assignment posted.')
            return redirect('assignment-list')
    else:
        form = AssignmentForm()
        # Teachers can only post to their own sections.
        if user_role(request.user) in ('faculty', 'staff'):
            try:
                from academics.models import CourseSection
                form.fields['section'].queryset = CourseSection.objects.filter(instructor=request.user.staff_profile)
            except Exception:
                pass
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Assignment', 'cancel_url': '/assignments/'})


@login_required
def submit_assignment(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students submit assignments.')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('assignment-list')

    existing = Submission.objects.filter(assignment=assignment, student=student).first()
    if request.method == 'POST':
        form = SubmissionForm(request.POST, request.FILES, instance=existing)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.assignment = assignment
            submission.student = student
            submission.save()
            messages.success(request, 'Assignment submitted.' + (' (late)' if submission.was_late else ''))
            return redirect('assignment-list')
    else:
        form = SubmissionForm(instance=existing)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Submit — {assignment.title}', 'cancel_url': '/assignments/'})


@staff_or_admin_required
def assignment_submissions(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk)
    if not can_manage_section(request.user, assignment.section):
        raise PermissionDenied('These submissions belong to another teacher\'s section.')
    submissions = assignment.submissions.select_related('student')
    return render(request, 'assignments/submissions.html', {'assignment': assignment, 'submissions': submissions})


@staff_or_admin_required
def grade_submission(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if not can_manage_section(request.user, submission.assignment.section, write=True):
        raise PermissionDenied('Only the section\'s own teacher can grade these submissions.')
    if request.method == 'POST':
        form = GradeSubmissionForm(request.POST, instance=submission)
        if form.is_valid():
            sub = form.save(commit=False)
            sub.graded_at = timezone.now()
            sub.save()
            notify(
                sub.student.user, f'Assignment graded: {sub.assignment.title}',
                f'You scored {sub.marks_obtained} / {sub.assignment.max_marks}.',
                level='info', url='/assignments/',
            )
            messages.success(request, 'Grade saved.')
            return redirect('assignment-submissions', pk=sub.assignment_id)
    else:
        form = GradeSubmissionForm(instance=submission)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Grade — {submission.student.full_name}', 'cancel_url': f'/assignments/{submission.assignment_id}/submissions/'})
