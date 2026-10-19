import biometrics.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('academics', '0004_courseregistration'),
        ('registration', '0003_student_address_student_cnic_student_phone'),
        ('exams', '0003_alter_gradeentry_attempt_type_retakeapplication'),
        ('onlineclass', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BiometricDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. "Room 204 Fingerprint Scanner"', max_length=150)),
                ('location', models.CharField(blank=True, max_length=200)),
                ('device_type', models.CharField(choices=[('fingerprint', 'Fingerprint Scanner'), ('face', 'Face Recognition'), ('hybrid', 'Fingerprint + Face')], default='fingerprint', max_length=20)),
                ('context', models.CharField(choices=[('physical_class', 'Physical Classroom Attendance'), ('exam', 'Exam Hall Attendance'), ('online_class', 'Online Class Check-In Kiosk'), ('general', 'General / Gate Attendance')], default='physical_class', max_length=20)),
                ('api_key', models.CharField(default=biometrics.models._generate_api_key, editable=False, max_length=64, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('section', models.ForeignKey(blank=True, help_text='For physical-classroom or online-class devices: which section this device covers.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='academics.coursesection')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='BiometricEnrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_user_id', models.CharField(help_text='The user ID assigned to this student on the device itself.', max_length=64)),
                ('enrolled_at', models.DateTimeField(auto_now_add=True)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='enrollments', to='biometrics.biometricdevice')),
                ('enrolled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='biometric_enrollments', to='registration.student')),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='biometricenrollment',
            unique_together={('device', 'device_user_id'), ('student', 'device')},
        ),
        migrations.CreateModel(
            name='BiometricPunch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_user_id', models.CharField(max_length=64)),
                ('matched', models.BooleanField(default=False)),
                ('applied_to', models.CharField(blank=True, help_text='What this punch resulted in, e.g. "AttendanceRecord #123".', max_length=100)),
                ('raw_payload', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('device', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='punches', to='biometrics.biometricdevice')),
                ('student', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='registration.student')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ExamAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('biometric_device', 'Hardware Biometric Device'), ('webauthn', 'WebAuthn (Browser Fingerprint/Face)'), ('manual', 'Manually Verified by Invigilator')], default='webauthn', max_length=20)),
                ('verified_at', models.DateTimeField(auto_now_add=True)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='biometric_attendance', to='exams.examsession')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exam_attendance', to='registration.student')),
                ('verified_by', models.ForeignKey(blank=True, help_text='Invigilator, for manual verification.', null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-verified_at']},
        ),
        migrations.AlterUniqueTogether(
            name='examattendance',
            unique_together={('exam', 'student')},
        ),
        migrations.CreateModel(
            name='OnlineClassAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('webauthn', 'WebAuthn (Browser Fingerprint/Face)'), ('biometric_device', 'Hardware Biometric Kiosk'), ('manual', 'Marked by Teacher')], default='webauthn', max_length=20)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('online_class', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance', to='onlineclass.onlineclass')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='online_class_attendance', to='registration.student')),
            ],
            options={'ordering': ['-joined_at']},
        ),
        migrations.AlterUniqueTogether(
            name='onlineclassattendance',
            unique_together={('online_class', 'student')},
        ),
    ]
