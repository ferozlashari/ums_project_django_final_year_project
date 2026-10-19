from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0002_attendancerecord_check_in_time_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attendancerecord',
            name='method',
            field=models.CharField(choices=[('manual', 'Marked by Teacher'), ('self_checkin', 'Self Check-In (Smart Attendance)'), ('biometric_webauthn', 'Biometric Verified (Fingerprint/Face via Browser)'), ('biometric_device', 'Biometric Verified (Hardware Scanner)')], default='manual', max_length=20),
        ),
    ]
