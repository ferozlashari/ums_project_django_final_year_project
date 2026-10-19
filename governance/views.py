from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Profile, log_action
from .constants import ACTIONS, MODULES
from .forms import AssignmentForm, PolicyVersionForm, RoleForm, SubAdminCreateForm
from .models import PolicyRule, Role, RoleAssignment, RolePermission
from .forms import EmergencyAccessForm
from .models import EmergencyAccess
from .permissions import provisionable_role_codes, all_sod_violations, has_perm, sod_conflicts, super_admin_required
from .policy import ensure_default_rules, new_version


@super_admin_required
def security_center(request):
    return render(request, 'governance/security-center.html', {
        'role_count': Role.objects.count(),
        'assignment_count': sum(1 for a in RoleAssignment.objects.select_related('role') if a.is_current()),
        'policy_count': PolicyRule.objects.count(),
        'recent': RoleAssignment.objects.select_related('user', 'role')[:10],
    })


@super_admin_required
def role_list(request):
    return render(request, 'governance/role-list.html', {'roles': Role.objects.prefetch_related('permissions')})


@super_admin_required
def role_edit(request, pk=None):
    role = get_object_or_404(Role, pk=pk) if pk else None
    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            posted_pairs = {(m, a) for m, _ in MODULES for a, _ in ACTIONS if request.POST.get(f'perm_{m}__{a}')}
            conflicts = sod_conflicts(posted_pairs)
            if conflicts:
                for label in conflicts:
                    messages.error(request, f'Separation of duties - a single role cannot bundle these: {label}.')
                return redirect(request.path)
            with transaction.atomic():
                old = role.permission_pairs() if role else set()
                saved = form.save(commit=False)
                if role is None:
                    saved.created_by = request.user
                saved.save()
                posted = {(m, a) for m, _ in MODULES for a, _ in ACTIONS if request.POST.get(f'perm_{m}__{a}')}
                for p in list(saved.permissions.all()):
                    if (p.module, p.action) not in posted:
                        p.delete()
                for module, action in posted - saved.permission_pairs():
                    RolePermission.objects.create(role=saved, module=module, action=action)
            log_action(request.user, 'ROLE_CHANGED' if role else 'ROLE_CREATED', obj=saved.name,
                       changes={'added': sorted(f'{m}.{a}' for m, a in posted - old),
                                'removed': sorted(f'{m}.{a}' for m, a in old - posted)}, request=request)
            messages.success(request, f'Role "{saved.name}" saved.')
            return redirect('role-list')
    else:
        form = RoleForm(instance=role)
    granted = role.permission_pairs() if role else set()
    matrix = [{'module': m, 'label': label,
               'cells': [{'action': a, 'checked': (m, a) in granted} for a, _ in ACTIONS]} for m, label in MODULES]
    return render(request, 'governance/role-edit.html', {'form': form, 'role': role, 'matrix': matrix, 'actions': ACTIONS})


@super_admin_required
@require_POST
def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if role.is_system:
        messages.error(request, 'System roles cannot be deleted - deactivate it instead.')
    elif role.assignments.exists():
        messages.error(request, 'This role is still assigned to users. Revoke the assignments first.')
    else:
        name = role.name
        role.delete()
        log_action(request.user, 'ROLE_DELETED', obj=name, request=request)
        messages.success(request, f'Role "{name}" deleted.')
    return redirect('role-list')


@super_admin_required
def assignment_list(request):
    return render(request, 'governance/assignment-list.html', {
        'assignments': RoleAssignment.objects.select_related('user', 'role', 'granted_by')})


@super_admin_required
def assignment_add(request):
    if request.method == 'POST':
        form = AssignmentForm(request.POST)
        if form.is_valid():
            a = form.save(commit=False)
            a.granted_by = request.user
            a.save()
            log_action(request.user, 'ROLE_ASSIGNED', obj=f'{a.user} -> {a.role}',
                       changes={'scope': [a.scope_type, a.scope_id], 'end_date': a.end_date}, request=request)
            messages.success(request, 'Role assigned.')
            return redirect('role-assignments')
    else:
        form = AssignmentForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Assign a role to an existing user', 'cancel_url': '/governance/assignments/'})


@super_admin_required
@require_POST
def assignment_revoke(request, pk):
    a = get_object_or_404(RoleAssignment, pk=pk)
    a.is_active = False
    a.save(update_fields=['is_active'])
    log_action(request.user, 'ROLE_REVOKED', obj=f'{a.user} -> {a.role}', request=request)
    messages.success(request, 'Assignment revoked.')
    return redirect('role-assignments')


@super_admin_required
def subadmin_create(request):
    """Create a brand-new restricted sub-admin and give it one role."""
    if request.method == 'POST':
        form = SubAdminCreateForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            with transaction.atomic():
                user = User.objects.create_user(username=d['username'], password=d['password'], email=d['email'],
                                                first_name=d['first_name'], last_name=d['last_name'])
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = 'staff'   # NOT is_staff/is_superuser: only its role's permissions apply
                profile.save()
                RoleAssignment.objects.create(user=user, role=d['role'], scope_type=d['scope_type'], scope_id=d['scope_id'],
                                              end_date=d['end_date'], granted_by=request.user, reason='Created as sub-administrator')
            log_action(request.user, 'USER_CREATED', obj=f'{user.username} (sub-admin: {d["role"]})', request=request)
            messages.success(request, f'Sub-admin "{user.username}" created with role {d["role"]}.')
            return redirect('role-assignments')
    else:
        form = SubAdminCreateForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Create sub-administrator account', 'cancel_url': '/governance/'})


@super_admin_required
def policy_center(request):
    ensure_default_rules()
    if request.method == 'POST':
        form = PolicyVersionForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            v = new_version(d['rule'], d['value'], user=request.user, scope_type=d['scope_type'], scope_id=d['scope_id'],
                            effective_from=d['effective_from'], effective_until=d['effective_until'], reason=d['reason'])
            log_action(request.user, 'POLICY_CHANGED', obj=str(v), reason=d['reason'], request=request)
            messages.success(request, f'{d["rule"].name}: version {v.version} created (older versions kept as history).')
            return redirect('policy-center')
    else:
        form = PolicyVersionForm()
    return render(request, 'governance/policy-center.html', {'form': form, 'rules': PolicyRule.objects.prefetch_related('versions')})


# ---------------------------------------------------------------------------
# Visibility pages: who may do what, and how the university is organised
# ---------------------------------------------------------------------------
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .constants import OFFICES, SOD_RULES
from .permissions import _current_assignments, authority_perm


def _can_see_people(user):
    return user.is_superuser or has_perm(user, 'security', 'view') or has_perm(user, 'executive', 'view') or has_perm(user, 'audit', 'view')


@login_required
def governance_map(request):
    """University structure + office/role map + lifecycle diagrams (all live data)."""
    from academics.models import Course, Faculty
    show_people = _can_see_people(request.user)
    faculties = []
    for f in Faculty.objects.prefetch_related('departments__programs').order_by('name'):
        depts = []
        for d in f.departments.all():
            depts.append({'dept': d, 'programs': list(d.programs.all()),
                          'course_count': Course.objects.filter(program__department=d).count()})
        faculties.append({'faculty': f, 'departments': depts})
    holders = {}
    if show_people:
        for a in RoleAssignment.objects.filter(is_active=True).select_related('user', 'role'):
            if a.is_current():
                holders.setdefault(a.role_id, []).append(a)
    offices = []
    for code, label in OFFICES:
        roles = []
        for r in Role.objects.filter(office=code, is_active=True).prefetch_related('permissions').order_by('rank', 'name'):
            roles.append({'role': r, 'perm_count': len(r.permissions.all()), 'holders': holders.get(r.pk, []),
                          'modules': sorted({p.module for p in r.permissions.all()})})
        offices.append({'code': code, 'label': label, 'roles': roles})
    return render(request, 'governance/map.html', {
        'faculties': faculties, 'offices': offices, 'show_people': show_people,
        'unassigned': Role.objects.filter(office='', is_active=True),
    })


@login_required
def my_access(request):
    """Every user can see exactly what their account is allowed to do."""
    user = request.user
    rows = []
    for a in _current_assignments(user):
        grouped = {}
        for p in a.role.permissions.all():
            grouped.setdefault(p.get_module_display(), []).append(p.get_action_display())
        rows.append({'assignment': a, 'grouped': sorted(grouped.items())})
    from core.permissions import user_role
    return render(request, 'governance/my-access.html', {
        'rows': rows, 'role': user_role(user), 'is_super': user.is_superuser,
        'modules': dict(MODULES)})


@login_required
def permission_matrix(request):
    if not (request.user.is_superuser or has_perm(request.user, 'security', 'view') or has_perm(request.user, 'audit', 'view')):
        raise PermissionDenied('Only security, audit or system administrators can view the permission matrix.')
    roles = list(Role.objects.filter(is_active=True).prefetch_related('permissions'))
    table = []
    for module, label in MODULES:
        cells = []
        for r in roles:
            acts = sorted(p.action for p in r.permissions.all() if p.module == module)
            cells.append(', '.join(acts))
        table.append({'label': label, 'cells': cells})
    return render(request, 'governance/matrix.html', {'roles': roles, 'table': table, 'rules': SOD_RULES,
                                                      'violations': all_sod_violations()})


@login_required
def executive_dashboard(request):
    """Oversight for the Chancellor / VC: read-only totals, queues and exceptions."""
    if not (request.user.is_superuser or has_perm(request.user, 'executive', 'view')):
        raise PermissionDenied('The executive dashboard is for university oversight roles.')
    from academics.models import Course, Faculty, Program
    from admissions.models import Application
    from core.models import AuditLog
    from exams.models import ResultPublication
    from finance.models import Invoice
    from hr.models import Staff
    from registration.models import Student
    from workflow.models import WorkflowRequest
    since = timezone.now() - timezone.timedelta(days=30)
    unpaid = Invoice.objects.filter(paid=False)
    stats = [
        ('Students', Student.objects.count()), ('Faculty & staff', Staff.objects.count()),
        ('Faculties', Faculty.objects.count()), ('Programs', Program.objects.count()),
        ('Courses', Course.objects.count()),
        ('Applications pending', Application.objects.filter(status='pending').count()),
        ('Results awaiting publication', ResultPublication.objects.exclude(status='published').count()),
        ('Unpaid invoices', unpaid.count()),
        ('Approvals pending', WorkflowRequest.objects.filter(status='pending').count()),
    ]
    break_glass = AuditLog.objects.filter(action__in=['BREAK_GLASS_APPROVAL', 'EMERGENCY_ACCESS_GRANTED'], created_at__gte=since).count()
    return render(request, 'governance/executive.html', {
        'stats': stats, 'break_glass': break_glass, 'violations': all_sod_violations(),
        'recent': AuditLog.objects.select_related('actor')[:12],
        'escalations': WorkflowRequest.objects.filter(status='pending', request_type='refund').count(),
        'can_decide': authority_perm(request.user, 'executive', 'approve')[0]})


@super_admin_required
def emergency_access(request):
    """Break-glass: the System Administrator asks, with a reason, for a short window."""
    if request.method == 'POST':
        if request.POST.get('revoke'):
            grant = get_object_or_404(EmergencyAccess, pk=request.POST['revoke'], user=request.user, revoked_at__isnull=True)
            grant.revoked_at = timezone.now()
            grant.save(update_fields=['revoked_at'])
            log_action(request.user, 'EMERGENCY_ACCESS_REVOKED', obj=str(grant), request=request)
            messages.info(request, 'Emergency access ended.')
            return redirect('emergency-access')
        form = EmergencyAccessForm(request.POST)
        if form.is_valid():
            grant = EmergencyAccess.objects.create(
                user=request.user, reason=form.cleaned_data['reason'],
                expires_at=timezone.now() + timezone.timedelta(minutes=form.cleaned_data['minutes']))
            log_action(request.user, 'EMERGENCY_ACCESS_GRANTED', obj=str(grant), reason=grant.reason, request=request)
            messages.warning(request, f'Emergency access is active until {grant.expires_at:%H:%M}. Every action taken with it is audited.')
            return redirect('emergency-access')
    else:
        form = EmergencyAccessForm()
    return render(request, 'governance/emergency.html', {
        'form': form, 'grants': EmergencyAccess.objects.select_related('user')[:30], 'now': timezone.now()})


@login_required
def provision_account(request):
    """Delegated account creation: each office head can create accounts only for
    the roles that belong under them (see constants.PROVISIONING)."""
    codes = provisionable_role_codes(request.user)
    if not codes:
        raise PermissionDenied('You are not authorised to create accounts for any office.')
    allowed = Role.objects.filter(code__in=codes, is_active=True)
    if request.method == 'POST':
        form = SubAdminCreateForm(request.POST)
        form.fields['role'].queryset = allowed
        if form.is_valid():
            d = form.cleaned_data
            with transaction.atomic():
                user = User.objects.create_user(username=d['username'], password=d['password'], email=d['email'],
                                                first_name=d['first_name'], last_name=d['last_name'])
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = 'staff'
                profile.save()
                RoleAssignment.objects.create(user=user, role=d['role'], scope_type=d['scope_type'], scope_id=d['scope_id'],
                                              end_date=d['end_date'], granted_by=request.user,
                                              reason=f'Provisioned by {request.user.username}')
            log_action(request.user, 'USER_PROVISIONED', obj=f'{user.username} ({d["role"]})', request=request)
            messages.success(request, f'Account "{user.username}" created as {d["role"]}.')
            return redirect('provision-account')
    else:
        form = SubAdminCreateForm()
        form.fields['role'].queryset = allowed
    return render(request, 'core/form_base.html', {
        'form': form, 'title': 'Create an office account', 'cancel_url': '/governance/my-access/',
        'subtitle': 'You can only create accounts for: ' + ', '.join(r.name for r in allowed)})
