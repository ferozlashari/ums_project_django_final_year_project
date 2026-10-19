"""Object/scope aware permission checks.

  * Django superuser  = System Administrator, unrestricted.
  * Anyone holding RoleAssignments is a SUB-ADMIN limited to exactly what
    those current, in-scope roles grant - even if also flagged is_staff.
  * A non-superuser staff flag NEVER grants unrestricted administration.
    Administrative access comes only from an explicit RoleAssignment.
  * Everyone else (teachers, students, ...) has no administrative permission.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import RoleAssignment


def _current_assignments(user):
    qs = RoleAssignment.objects.filter(user=user, is_active=True, role__is_active=True).select_related('role')
    return [a for a in qs if a.is_current()]


def _scope_ok(a, program=None, department=None, faculty=None):
    if a.scope_type == 'university':
        return True
    if a.scope_type == 'program':
        return program is not None and program.pk == a.scope_id
    dept = department or getattr(program, 'department', None)
    if a.scope_type == 'department':
        return dept is not None and dept.pk == a.scope_id
    if a.scope_type == 'faculty':
        fac = faculty or getattr(dept, 'faculty', None)
        return fac is not None and fac.pk == a.scope_id
    return False


def is_super_admin(user):
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def has_perm(user, module, action, program=None, department=None, faculty=None):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    assignments = _current_assignments(user)
    if assignments:
        return any(_scope_ok(a, program, department, faculty) and
                   a.role.permissions.filter(module=module, action=action).exists()
                   for a in assignments)
    return False


def perm_required(module, action):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not has_perm(request.user, module, action):
                raise PermissionDenied(f'You do not have permission to {action} {module}.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def super_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_super_admin(request.user):
            raise PermissionDenied('Only the System Administrator can do this.')
        return view(request, *args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Authority checks (separation of duties)
# ---------------------------------------------------------------------------
def _holders_exist(module, action):
    """True if at least one non-superuser currently holds module.action."""
    from .models import RolePermission
    role_ids = RolePermission.objects.filter(module=module, action=action, role__is_active=True).values_list('role_id', flat=True)
    for a in RoleAssignment.objects.filter(role_id__in=list(role_ids), is_active=True, user__is_active=True,
                                           user__is_superuser=False).select_related('role'):
        if a.is_current():
            return True
    return False


def authority_perm(user, module, action, **scope):
    """Decide whether `user` may exercise *decision authority* (approve / verify /
    publish ...).

    * A person holding the office role with the right scope: always allowed.
    * The System Administrator is the IT/system owner, not a university officer.
      They may act only as a logged BREAK-GLASS fallback, and only when nobody in
      the university has been given that authority yet (so a small installation
      still works). Once an office holder exists, the System Administrator can no
      longer approve in that office's place.

    Returns (allowed: bool, break_glass: bool).
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False, False
    if user.is_superuser:
        # The system owner has no university authority of their own. Emergency
        # access needs (1) nobody holds this authority AND (2) an explicit,
        # reasoned, time-limited, audited EmergencyAccess grant.
        if _holders_exist(module, action) or not has_emergency_access(user):
            return False, False
        return True, True
    return has_perm(user, module, action, **scope), False


def has_emergency_access(user):
    from django.utils import timezone
    from .models import EmergencyAccess
    return EmergencyAccess.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now()).exists()


# ---------------------------------------------------------------------------
# Separation-of-duties analysis
# ---------------------------------------------------------------------------
def sod_conflicts(pairs):
    """Return the list of SoD rule labels violated by a set of (module, action) pairs."""
    from .constants import SOD_RULES
    pairs = set(pairs)
    found = []
    for label, side_a, side_b in SOD_RULES:
        a_hit = [p for p in side_a if p in pairs]
        b_hit = [p for p in side_b if p in pairs]
        if a_hit and b_hit:
            found.append(label)
    return found


def user_permission_pairs(user, exclude_assignment_id=None):
    pairs = set()
    for a in _current_assignments(user):
        if exclude_assignment_id and a.pk == exclude_assignment_id:
            continue
        pairs |= a.role.permission_pairs()
    return pairs


def user_sod_conflicts(user, extra_role=None):
    pairs = user_permission_pairs(user)
    if extra_role is not None:
        pairs |= extra_role.permission_pairs()
    return sod_conflicts(pairs)


def all_sod_violations():
    """[(user, [labels])] for every non-superuser who currently holds conflicting duties."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    ids = RoleAssignment.objects.filter(is_active=True).values_list('user_id', flat=True).distinct()
    out = []
    for u in User.objects.filter(pk__in=list(ids), is_active=True, is_superuser=False):
        labels = user_sod_conflicts(u)
        if labels:
            out.append((u, labels))
    return out


def provisionable_role_codes(user):
    """Role codes `user` may create accounts for (empty for most people)."""
    from .constants import PROVISIONING
    if not user.is_authenticated:
        return set()
    codes = set()
    for (module, action), roles in PROVISIONING.items():
        if has_perm(user, module, action) and not user.is_superuser:
            codes.update(roles)
    return codes


def has_perm_anywhere(user, module, action):
    """True if any current assignment (at any scope) grants module.action.
    Used only to decide whether to open a page; the data itself is still filtered by scope."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return any((module, action) in a.role.permission_pairs() for a in _current_assignments(user))
