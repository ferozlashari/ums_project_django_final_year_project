from .constants import DEFAULT_ROLES, ROLE_OFFICE
from .models import Role, RolePermission


def ensure_default_roles():
    """Install (or top up) every default office role. Existing roles keep any
    permissions the System Administrator customised; only missing office/rank
    metadata is filled in."""
    for code, (name, desc, perms) in DEFAULT_ROLES.items():
        office, rank = ROLE_OFFICE.get(code, ('', 100))
        role, created = Role.objects.get_or_create(
            code=code, defaults={'name': name, 'description': desc, 'is_system': True, 'office': office, 'rank': rank})
        if not created and not role.office and office:
            role.office, role.rank = office, rank
            role.save(update_fields=['office', 'rank'])
        if created or not role.permissions.exists():
            for module, actions in perms.items():
                for action in actions:
                    RolePermission.objects.get_or_create(role=role, module=module, action=action)
    return len(DEFAULT_ROLES)
