from django.db import migrations, models
from django.db.models import Q


def cleanup(apps, schema_editor):
    Model = apps.get_model('academics', 'CourseRegistration')
    seen = set()
    for row in Model.objects.filter(status='registered').order_by('registered_at', 'id'):
        key = (row.student_id, row.section_id)
        if key in seen:
            row.status = 'dropped'
            row.save(update_fields=['status'])
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [('academics', '0007_program_level_categories')]
    operations = [
        migrations.RunPython(cleanup, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='courseregistration',
            constraint=models.UniqueConstraint(condition=Q(status='registered'), fields=('student', 'section'), name='uniq_active_course_registration'),
        ),
        migrations.AddIndex(model_name='courseregistration', index=models.Index(fields=['student', 'status'], name='academics_c_student_9c3a9b_idx')),
        migrations.AddIndex(model_name='courseregistration', index=models.Index(fields=['section', 'status'], name='academics_c_section_6d9c55_idx')),
    ]
