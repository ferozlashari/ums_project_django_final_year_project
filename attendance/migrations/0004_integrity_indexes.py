from django.db import migrations, models


def cleanup(apps, schema_editor):
    Model = apps.get_model('attendance', 'AttendanceRecord')
    seen = set()
    for row in Model.objects.all().order_by('student_id', 'date', '-created_at', '-id'):
        key = (row.student_id, row.date)
        if key in seen:
            row.delete()
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [('attendance', '0003_attendancerecord_biometric_methods')]
    operations = [
        migrations.RunPython(cleanup, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='attendancerecord', constraint=models.UniqueConstraint(fields=('student', 'date'), name='uniq_student_attendance_day')),
        migrations.AddIndex(model_name='attendancerecord', index=models.Index(fields=['student', 'date'], name='attendance_s_student_5f7b3d_idx')),
        migrations.AddIndex(model_name='attendancerecord', index=models.Index(fields=['section', 'date'], name='attendance_s_section_7c3f0e_idx')),
    ]
