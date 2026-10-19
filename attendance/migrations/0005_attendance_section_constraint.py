from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('attendance','0004_integrity_indexes')]
    operations = [
        migrations.RemoveConstraint(model_name='attendancerecord', name='uniq_student_attendance_day'),
        migrations.AddConstraint(model_name='attendancerecord', constraint=models.UniqueConstraint(fields=('student','section','date'), condition=models.Q(section__isnull=False), name='uniq_student_section_attendance_day')),
    ]
