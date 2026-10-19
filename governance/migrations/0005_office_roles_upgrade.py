from django.db import migrations

# The default permissions these four roles shipped with before the office-based
# redesign. A role is only upgraded if it still matches this exactly, so any
# customisation made by a Super Administrator is never overwritten.
OLD_DEFAULTS = {
    'registrar': {'students': 'view create edit export print', 'admissions': 'view create edit approve reject publish',
                  'registration': 'view create edit approve override', 'reports': 'view export print generate'},
    'admission_officer': {'admissions': 'view create edit approve reject', 'students': 'view'},
    'exam_controller': {'exams': 'view create edit approve publish configure',
                        'results': 'view verify approve publish unpublish override export print',
                        'grade_policy': 'view configure', 'reports': 'view export'},
    'finance_officer': {'finance': 'view create edit approve void reconcile export print generate',
                        'scholarships': 'view', 'reports': 'view export'},
}


def _pairs(d):
    return {(m, a) for m, acts in d.items() for a in acts.split()}


def upgrade(apps, schema_editor):
    from governance.constants import DEFAULT_ROLES, ROLE_OFFICE
    Role = apps.get_model('governance', 'Role')
    RolePermission = apps.get_model('governance', 'RolePermission')
    for code, (name, desc, perms) in DEFAULT_ROLES.items():
        office, rank = ROLE_OFFICE.get(code, ('', 100))
        role, created = Role.objects.get_or_create(
            code=code, defaults={'name': name, 'description': desc, 'is_system': True, 'office': office, 'rank': rank})
        if not role.office:
            role.office, role.rank = office, rank
            role.save()
        new_pairs = {(m, a) for m, acts in perms.items() for a in acts}
        have = set(RolePermission.objects.filter(role=role).values_list('module', 'action'))
        if created or not have:
            for m, a in new_pairs - have:
                RolePermission.objects.get_or_create(role=role, module=m, action=a)
        elif code in OLD_DEFAULTS and have == _pairs(OLD_DEFAULTS[code]):
            RolePermission.objects.filter(role=role).delete()
            role.name, role.description = name, desc
            role.save()
            for m, a in new_pairs:
                RolePermission.objects.get_or_create(role=role, module=m, action=a)


class Migration(migrations.Migration):
    dependencies = [('governance', '0004_role_office_rank')]
    operations = [migrations.RunPython(upgrade, migrations.RunPython.noop)]
