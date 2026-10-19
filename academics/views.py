from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.views.decorators.http import require_POST
from .models import Course, Department, Faculty, Program, CourseSection
from .forms import CourseForm, DepartmentForm, FacultyForm, ProgramForm, CourseSectionForm
from core.permissions import staff_or_admin_required, admin_required
from governance.permissions import perm_required


@login_required
def course_list(request):
    query = request.GET.get('q', '').strip()
    courses = Course.objects.select_related('program').all()
    if query:
        courses = courses.filter(name__icontains=query) | courses.filter(code__icontains=query)
    return render(request, 'core/course-allocation.html', {'courses': courses, 'query': query})


@perm_required('courses', 'create')
def course_add(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course added.')
            return redirect('course-list')
    else:
        form = CourseForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Course', 'cancel_url': '/academics/courses/'})


@perm_required('courses', 'edit')
def course_edit(request, pk):
    c = get_object_or_404(Course, pk=pk)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=c)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course updated.')
            return redirect('course-list')
    else:
        form = CourseForm(instance=c)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Course', 'cancel_url': '/academics/courses/'})


@login_required
def department_list(request):
    departments = Department.objects.select_related('faculty').all()
    return render(request, 'academics/department-list.html', {'departments': departments})


@perm_required('programs', 'create')
def department_add(request):
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department added.')
            return redirect('department-list')
    else:
        form = DepartmentForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Department', 'cancel_url': '/academics/departments/'})


@perm_required('programs', 'edit')
def department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=dept)
        if form.is_valid():
            form.save()
            messages.success(request, 'Department updated.')
            return redirect('department-list')
    else:
        form = DepartmentForm(instance=dept)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Department', 'cancel_url': '/academics/departments/'})


@login_required
def faculty_list(request):
    faculties = Faculty.objects.all()
    return render(request, 'academics/faculty-list.html', {'faculties': faculties})


@perm_required('programs', 'create')
def faculty_add(request):
    if request.method == 'POST':
        form = FacultyForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faculty added.')
            return redirect('faculty-list')
    else:
        form = FacultyForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Faculty', 'cancel_url': '/academics/faculties/'})


@perm_required('programs', 'edit')
def faculty_edit(request, pk):
    faculty = get_object_or_404(Faculty, pk=pk)
    if request.method == 'POST':
        form = FacultyForm(request.POST, instance=faculty)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faculty updated.')
            return redirect('faculty-list')
    else:
        form = FacultyForm(instance=faculty)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Faculty', 'cancel_url': '/academics/faculties/'})


@login_required
def program_list(request):
    programs = Program.objects.select_related('department', 'department__faculty').all()
    return render(request, 'academics/program-list.html', {'programs': programs})


@perm_required('programs', 'create')
def program_add(request):
    if request.method == 'POST':
        form = ProgramForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Program added.')
            return redirect('program-list')
    else:
        form = ProgramForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Program', 'cancel_url': '/academics/programs/'})


@perm_required('programs', 'edit')
def program_edit(request, pk):
    program = get_object_or_404(Program, pk=pk)
    if request.method == 'POST':
        form = ProgramForm(request.POST, instance=program)
        if form.is_valid():
            form.save()
            messages.success(request, 'Program updated.')
            return redirect('program-list')
    else:
        form = ProgramForm(instance=program)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Program', 'cancel_url': '/academics/programs/'})


@staff_or_admin_required
def section_list(request):
    """The management view of course sections (create/edit/assign teacher/
    capacity) - distinct from browse_sections, which is the student-facing
    registration picker for sections in the active semester only. This one
    shows every section that exists, for admin/staff/faculty oversight."""
    sections = CourseSection.objects.select_related('course', 'instructor', 'instructor__user').all()
    return render(request, 'academics/section-list.html', {'sections': sections})


@perm_required('sections', 'create')
def section_add(request):
    if request.method == 'POST':
        form = CourseSectionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Section added.')
            return redirect('section-list')
    else:
        form = CourseSectionForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Section', 'cancel_url': '/academics/section-management/'})


@perm_required('sections', 'edit')
def section_edit(request, pk):
    section = get_object_or_404(CourseSection, pk=pk)
    if request.method == 'POST':
        form = CourseSectionForm(request.POST, instance=section)
        if form.is_valid():
            form.save()
            messages.success(request, 'Section updated.')
            return redirect('section-list')
    else:
        form = CourseSectionForm(instance=section)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Edit Section', 'cancel_url': '/academics/section-management/'})


def _registration_window_info(semester):
    """Human-facing summary of a semester's course-selection and drop windows
    for the banners on Course Selection / My Registrations."""
    from django.utils import timezone
    if semester is None:
        return None
    local = timezone.localtime
    return {
        'state': semester.registration_state(),
        'opens': local(semester.registration_open) if semester.registration_open else None,
        'closes': local(semester.registration_close) if semester.registration_close else None,
        'drop_state': semester.drop_state(),
        'drop_deadline': local(semester.effective_drop_deadline),
    }


@login_required
def browse_sections(request):
    """Students browse course sections available for their program and
    self-register (capped by section capacity)."""
    from django.contrib import messages as dj_messages
    from .models import CourseSection

    role = None
    try:
        from core.permissions import user_role
        role = user_role(request.user)
    except Exception:
        pass

    sections = CourseSection.objects.select_related('course', 'course__program', 'course__program__department', 'instructor', 'instructor__user').all()
    my_section_ids = set()
    student_program_id = None
    if role == 'student':
        try:
            student = request.user.student_profile
            if student.active_program_id:
                student_program_id = student.active_program_id
        except Exception:
            pass

    # Filter by department/degree - defaults to the student's own program so
    # nothing changes for anyone who doesn't touch the filter, but electives
    # or cross-department options are just a dropdown away instead of
    # requiring an admin to intervene.
    from .models import Department, Program
    department_filter = request.GET.get('department', '').strip()
    program_filter = request.GET.get('program', '').strip()
    if program_filter:
        sections = sections.filter(course__program_id=program_filter)
    elif department_filter:
        sections = sections.filter(course__program__department_id=department_filter)
    elif student_program_id:
        sections = sections.filter(course__program_id=student_program_id)

    # Students must only see courses that are actually eligible now. The
    # deterministic service applies semester, curriculum, prerequisite,
    # duplicate, capacity and credit-limit rules server-side.
    current_semester = None
    viewing_semester = None
    all_semesters = None
    credits_registered = 0
    credit_limit = None
    student_obj = None
    if role == 'student':
        try:
            from core.services.academic import AcademicEligibilityService
            from core.models import SiteSettings
            from .models import Semester
            from registration.models import Student
            student_obj = request.user.student_profile
            current_semester = AcademicEligibilityService.current_semester()

            # Viewing a different semester is just a filter (e.g. checking
            # what an upcoming semester's course list looks like, or what
            # was offered in a past one) - it never changes what's
            # actually registerable, since registration_eligibility below
            # still enforces that semester's own registration window.
            all_semesters = Semester.objects.select_related('session').order_by('-start_date')[:12]
            semester_id = request.GET.get('semester', '').strip()
            if semester_id:
                # Look up the requested semester from the full table, not
                # from `all_semesters` above - that queryset is already
                # sliced (for the dropdown, top 12 by date), and Django
                # raises "Cannot filter a query once a slice has been
                # taken" if you try to .filter() a sliced queryset, so the
                # chosen semester is fetched with its own query instead.
                viewing_semester = Semester.objects.filter(pk=semester_id).first() or current_semester
            else:
                viewing_semester = current_semester

            credit_limit = int(SiteSettings.load().max_registration_credits)
            # Both values are scoped to the semester being viewed, so the
            # "Registered" marker and the credit total always agree.
            my_section_ids = set(
                student_obj.course_registrations.filter(status='registered', semester=viewing_semester).values_list('section_id', flat=True)
            ) if viewing_semester else set()
            credits_registered = sum(
                (r.section.course.credits or 0)
                for r in student_obj.course_registrations.filter(status='registered', semester=viewing_semester).select_related('section__course')
            ) if viewing_semester else 0
            eligible_ids = [
                sec.id for sec in sections.prefetch_related('course__prerequisites')
                if AcademicEligibilityService.registration_eligibility(student_obj, sec, viewing_semester).eligible
            ]
            sections = sections.prefetch_related('course__prerequisites').filter(id__in=eligible_ids)
        except Student.DoesNotExist:
            # Expected/business case: a student-role account with no
            # linked Student record yet - show an empty list, not an error.
            sections = sections.none()
        except Exception:
            # Unexpected error: log it so it can be fixed instead of silently
            # reporting "nothing is eligible", and degrade to an empty list
            # rather than a 500, since this is a browse page.
            import logging
            logging.getLogger('ums.errors').exception(
                'browse_sections failed to compute eligible sections for user=%s', request.user
            )
            sections = sections.none()

    return render(request, 'academics/browse-sections.html', {
        'sections': sections, 'my_section_ids': my_section_ids, 'role': role,
        'departments': Department.objects.select_related('faculty').all(),
        'programs': Program.objects.select_related('department').all(),
        'department_filter': department_filter, 'program_filter': program_filter,
        'current_semester': current_semester, 'viewing_semester': viewing_semester,
        'all_semesters': all_semesters, 'student': student_obj,
        'credits_registered': credits_registered, 'credit_limit': credit_limit,
        'window': _registration_window_info(viewing_semester),
    })


@login_required
@require_POST
def register_section(request, section_id):
    from django.contrib import messages as dj_messages
    from core.permissions import user_role
    from core.services.academic import AcademicEligibilityService

    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students can register for courses.')
    try:
        student = request.user.student_profile
    except Exception:
        dj_messages.error(request, 'No student record linked to this account.')
        return redirect('browse-sections')
    try:
        semester_id = request.POST.get('semester_id', '').strip()
        semester = None
        if semester_id:
            from .models import Semester
            semester = Semester.objects.filter(pk=semester_id).first()
        registration = AcademicEligibilityService.register_course(student, section_id, semester)
    except ValueError as exc:
        dj_messages.error(request, str(exc))
        return redirect('browse-sections')
    except Exception:
        dj_messages.error(request, 'Registration could not be completed. Please try again.')
        return redirect('browse-sections')
    from core.models import notify
    notify(request.user, 'Course registration successful', f'{registration.section.course.code} - {registration.section.code} was registered for {registration.semester}.', level='success', url='/academics/my-registrations/')
    dj_messages.success(request, f'Registered for {registration.section.course.code} - {registration.section.code}.')
    return redirect('my-registrations')

@login_required
def my_registrations(request):
    from django.utils import timezone
    try:
        student = request.user.student_profile
        registrations = list(student.course_registrations.filter(status='registered').select_related('section__course', 'section__instructor', 'semester'))
    except Exception:
        registrations = []
    for r in registrations:
        r.can_drop = r.semester is None or r.semester.drop_state() == 'open'
    semesters = {r.semester for r in registrations if r.semester}
    windows = [{
        'semester': sem,
        'drop_deadline': timezone.localtime(sem.effective_drop_deadline),
        'drop_open': sem.drop_state() == 'open',
    } for sem in sorted(semesters, key=lambda x: x.start_date, reverse=True)]
    return render(request, 'academics/my-registrations.html', {'registrations': registrations, 'windows': windows})


@login_required
@require_POST
def drop_registration(request, pk):
    """Drop a course - only inside the semester's drop window, and never once
    the course has a recorded grade. The deadline comes from
    Semester.effective_drop_deadline (explicit drop deadline, else the
    registration close, else the Site Settings default), so it can never be
    silently unlimited."""
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    from django.contrib import messages as dj_messages
    from django.utils import timezone
    from .models import CourseRegistration

    reg = get_object_or_404(CourseRegistration.objects.select_related('section__course', 'semester', 'student'), pk=pk)
    if reg.student.user_id != request.user.id:
        raise PermissionDenied("You can only drop your own course registrations.")
    if reg.status != 'registered':
        dj_messages.info(request, 'This course is already dropped.')
        return redirect('my-registrations')

    semester = reg.semester
    if semester is not None and semester.drop_state() == 'closed':
        deadline = timezone.localtime(semester.effective_drop_deadline)
        dj_messages.error(
            request,
            f'The drop deadline for {semester.display_name} passed on {deadline:%d %b %Y, %H:%M}, so '
            f'{reg.section.course.code} can no longer be dropped. Please contact the registrar if you have an exceptional case.',
        )
        return redirect('my-registrations')

    from exams.models import GradeEntry
    if GradeEntry.objects.filter(student=reg.student, exam__course=reg.section.course, exam__semester=semester).exists():
        dj_messages.error(request, f'{reg.section.course.code} already has a recorded result this semester and cannot be dropped.')
        return redirect('my-registrations')

    reg.status = 'dropped'
    reg.save(update_fields=['status'])
    dj_messages.success(request, f'Dropped {reg.section.course.code}.')
    return redirect('my-registrations')
