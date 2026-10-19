from django.db import migrations, models


def migrate_old_levels(apps, schema_editor):
    """Map the old ('ug', 'pg', 'phd') choices onto the new, more specific
    set so no existing Program silently ends up with an undisplayable
    level value. 'pg' (generic postgrad) becomes 'master', which is the
    overwhelmingly common case; anyone actually running an MPhil program
    can re-pick it manually in admin afterward."""
    Program = apps.get_model('academics', 'Program')
    Program.objects.filter(level='ug').update(level='bachelor')
    Program.objects.filter(level='pg').update(level='master')


def reverse_migrate_levels(apps, schema_editor):
    Program = apps.get_model('academics', 'Program')
    Program.objects.filter(level='bachelor').update(level='ug')
    Program.objects.filter(level__in=['master', 'mphil']).update(level='pg')


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0006_program_semester_fee'),
    ]

    operations = [
        migrations.AlterField(
            model_name='program',
            name='level',
            field=models.CharField(choices=[('bachelor', "Bachelor's (BS/BSc)"), ('master', "Master's (MS/MSc)"), ('mphil', 'MPhil'), ('phd', 'PhD')], default='bachelor', max_length=20),
        ),
        migrations.RunPython(migrate_old_levels, reverse_migrate_levels),
    ]
