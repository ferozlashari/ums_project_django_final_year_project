from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('attendance', '0008_alter_attendancerecord_method'), ('academics', '0014_alter_coursesection_options_alter_faculty_options')]
    operations = [
        migrations.CreateModel(
            name='AttendanceSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('attendance_type', models.CharField(choices=[('physical','Physical Class'),('online','Online Class'),('hybrid','Hybrid'),('qr','QR Check-in'),('biometric','Biometric Verification')], default='physical', max_length=20)),
                ('topic', models.CharField(blank=True, max_length=255)),
                ('is_open', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_sessions', to='academics.coursesection')),
                ('semester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_sessions', to='academics.semester')),
            ],
            options={'ordering': ['-date', '-created_at']},
        ),
        migrations.AddField(model_name='attendancerecord', name='semester', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_records', to='academics.semester')),
        migrations.AddField(model_name='attendancerecord', name='session', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='records', to='attendance.attendancesession')),
        migrations.AddField(model_name='attendancerecord', name='registration', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_records', to='academics.courseregistration')),
        migrations.AddIndex(model_name='attendancerecord', index=models.Index(fields=['student','semester'], name='attendance__student_semester_idx')),
        migrations.AddIndex(model_name='attendancerecord', index=models.Index(fields=['registration','date'], name='attendance__registration_date_idx')),
        migrations.AddIndex(model_name='attendancesession', index=models.Index(fields=['section','semester','date'], name='attendance__section_sem_date_idx')),
        migrations.AddIndex(model_name='attendancesession', index=models.Index(fields=['semester','date'], name='attendance__semester_date_idx')),
    ]
