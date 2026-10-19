"""
Role-based access control helpers, shared across every app.

Roles come from Profile.role. Django superusers are the only unrestricted
administrators. Non-superuser administrative accounts must also have an
explicit governance RoleAssignment; is_staff alone never grants full access.
"""
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'admin'
    try:
        role = user.profile.role
    except Exception:
        return 'staff' if user.is_staff else 'student'
    # only a Super Administrator is ever 'admin'. A stale/default profile role of 'admin' on a
    # non-superuser (e.g. any login created with "Staff status" ticked) must NOT grant the
    # unrestricted admin shortcut - such a login is a restricted staff account that needs
    # explicit governance permissions.
    if role == 'admin':
        return 'staff'
    return role


_GOVERNANCE_MODULES = {
    'academics': 'courses', 'admissions': 'admissions', 'registration': 'registration',
    'timetable': 'sections', 'exams': 'exams', 'finance': 'finance', 'hr': 'hr',
    'attendance': 'attendance', 'library': 'library', 'hostel': 'hostel',
    'complaints': 'students', 'scholarships': 'scholarships', 'classes': 'sections',
    'alumni': 'students', 'parents': 'students', 'careers': 'students',
    'risk': 'reports', 'biometrics': 'security', 'assignments': 'attendance',
    'quizzes': 'exams', 'oversight': 'data_quality', 'workflow': 'automation',
    'transport': 'transport', 'id': 'students', 'api': 'reports',
    'governance': 'security', 'core': 'settings',
}


def _governance_request_permission(request, default_action='view'):
    """Translate an application route into a conservative governance check.

    This is used only for non-superuser sub-admins. Teachers/staff without a
    governance assignment continue through their normal operational roles.
    """
    from governance.permissions import has_perm
    path = (request.path or '').strip('/').split('/')
    segment = path[0] if path else 'core'
    module = _GOVERNANCE_MODULES.get(segment)
    if segment == 'settings' or request.path.startswith('/settings/'):
        module = 'settings'
    if request.path.startswith('/audit-log'):
        module = 'audit'
    if request.path.startswith('/automation'):
        module = 'automation'
    if request.path.startswith('/reports'):
        module = 'reports'
    if request.path.startswith('/governance/policies'):
        module = 'policy'
    if not module:
        return False
    lower = request.path.lower()
    action = default_action
    for needle, candidate in (
        ('delete', 'delete'), ('remove', 'delete'), ('approve', 'approve'),
        ('reject', 'reject'), ('publish', 'publish'), ('unpublish', 'unpublish'),
        ('verify', 'verify'), ('override', 'override'), ('assign', 'assign'),
        ('export', 'export'), ('import', 'import'), ('reconcile', 'reconcile'),
        ('void', 'void'), ('configure', 'configure'), ('add', 'create'),
        ('new', 'create'), ('create', 'create'),
    ):
        if needle in lower:
            action = candidate
            break
    elif_method = request.method == 'POST'
    if elif_method and action == 'view':
        action = 'edit'
    return has_perm(request.user, module, action)


def webauthn_recently_verified(request):
    """True if the signed-in user completed a WebAuthn 'verify identity'
    check (see core.webauthn_views.webauthn_verify_complete) within the
    last 60 seconds. Consumes the flag on success so it can't be replayed
    for a second action."""
    raw = request.session.get('webauthn_verified_until')
    if not raw:
        return False
    from django.utils import timezone
    from datetime import datetime
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if timezone.now() > deadline:
        request.session.pop('webauthn_verified_until', None)
        return False
    request.session.pop('webauthn_verified_until', None)  # one-time use
    return True


def role_required(*roles):
    """Restrict a view by operational role while keeping sub-admin access scoped."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            role = user_role(request.user)
            if role == 'admin':
                return view_func(request, *args, **kwargs)
            # A staff-profile sub-admin must prove an explicit governance
            # permission. Never treat is_staff as a wildcard.
            if role == 'staff':
                from governance.models import RoleAssignment
                if RoleAssignment.objects.filter(user=request.user, is_active=True, role__is_active=True).exists():
                    if _governance_request_permission(request, 'view'):
                        return view_func(request, *args, **kwargs)
                    raise PermissionDenied("Your administrator account is not permitted to access this function.")
            if role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You don't have permission to access this page.")
        return _wrapped
    return decorator


# Common shortcuts
admin_required = role_required()            # admin only (role in roles=() is never true, only the is_staff shortcut matches)
staff_or_admin_required = role_required('faculty', 'staff')   # teachers/staff + admin - despite the name, this deliberately also covers faculty (e.g. grading their own courses). Use office_staff_required below when you specifically mean the non-teaching 'staff' role and NOT faculty.
office_staff_required = role_required('staff')   # non-teaching (admin office) staff + admin - explicitly excludes faculty


def staff_department(user):
    """Return the academics.Department a faculty/staff user belongs to, or None."""
    try:
        return user.staff_profile.department
    except Exception:
        return None


def department_scope_students(user, queryset):
    """Restrict a Student queryset to the signed-in teacher's own department.

    Admins are not filtered here (call sites decide whether to call this at
    all for admins). Faculty/staff with no department on file see nobody
    rather than everybody, so a missing profile can never leak the full
    roster. `queryset` must be filterable on `program__department`.
    """
    dept = staff_department(user)
    if dept is None:
        return queryset.none()
    return queryset.filter(program__department=dept)


def teaching_sections(user):
    """CourseSections the signed-in faculty/staff user actually teaches, or
    an empty queryset for anyone else / anyone with no staff profile."""
    from academics.models import CourseSection
    try:
        return CourseSection.objects.filter(instructor=user.staff_profile)
    except Exception:
        return CourseSection.objects.none()


def section_scope_students(user, queryset):
    """Restrict a Student queryset to only students *registered in a
    section the signed-in teacher actually teaches* - not the whole
    department. This is deliberately narrower than department_scope_students:
    a teacher's day-to-day work (recording attendance, entering grades)
    should only ever touch their own class roster, never a colleague's
    students in the same department. `queryset` must be a Student queryset.
    """
    sections = teaching_sections(user)
    if not sections.exists():
        return queryset.none()
    from academics.models import CourseRegistration
    student_ids = CourseRegistration.objects.filter(
        section__in=sections, status='registered',
    ).values_list('student_id', flat=True)
    return queryset.filter(id__in=student_ids)


# ---------------------------------------------------------------------------
# Object-level access (anti-IDOR). Hiding a button is not security: every view
# that takes an id must ask one of these before showing or changing anything.
# ---------------------------------------------------------------------------
def teaches_section(user, section):
    """True only for the instructor assigned to exactly this section."""
    return bool(section) and teaching_sections(user).filter(pk=section.pk).exists()


def can_manage_section(user, section, write=False):
    """Teaching content (assignments, quizzes, online classes, submissions).

    Writing: only the section's own instructor. Reading: the instructor, or an
    office holder (Dean/HOD/Registrar...) whose `sections` permission covers the
    section's program/department. Nobody else - not another teacher, not finance,
    not the IT administrator."""
    if not user.is_authenticated:
        return False
    if teaches_section(user, section):
        return True
    if write:
        return False
    from governance.permissions import has_perm
    course = section.course
    return has_perm(user, 'sections', 'view', program=course.program, department=course.program.department)


def teaches_grade(user, grade):
    """The teacher of the section this student is registered in for this exam's course."""
    from academics.models import CourseRegistration
    sections = teaching_sections(user)
    if grade.registration_id:
        return sections.filter(pk=grade.registration.section_id).exists()
    return CourseRegistration.objects.filter(
        student_id=grade.student_id, section__in=sections, section__course_id=grade.exam.course_id).exists()


def can_view_student(user, student, module='students'):
    """May `user` open this one student's record / documents?

    student -> their own; guardian -> a verified linked student; teacher -> only
    students registered in a section they teach; office roles -> only if they hold
    `module.view` for the student's program/department. System administrators get
    no automatic access to academic records."""
    if not user.is_authenticated:
        return False
    if student.user_id == user.id:
        return True
    role = user_role(user)
    if role == 'student':
        return False
    if role == 'guardian':
        return student.guardian_links.filter(guardian=user, verified_by__isnull=False).exists() if hasattr(student, 'guardian_links') else False
    if role == 'faculty' and section_scope_students(user, type(student).objects.filter(pk=student.pk)).exists():
        return True                                  # a teacher's own class roster
    from governance.permissions import has_perm
    program = student.active_program
    return has_perm(user, module, 'view', program=program, department=program.department if program else None)
