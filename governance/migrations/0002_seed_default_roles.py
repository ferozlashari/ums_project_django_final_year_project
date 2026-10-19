from django.db import migrations


def seed(apps, schema_editor):
    from governance.constants import DEFAULT_ROLES
    Role = apps.get_model('governance', 'Role')
    RolePermission = apps.get_model('governance', 'RolePermission')
    for code, (name, desc, perms) in DEFAULT_ROLES.items():
        role, _ = Role.objects.get_or_create(code=code, defaults={'name': name, 'description': desc, 'is_system': True})
        for module, actions in perms.items():
            for action in actions:
                RolePermission.objects.get_or_create(role=role, module=module, action=action)


class Migration(migrations.Migration):
    dependencies = [('governance', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
