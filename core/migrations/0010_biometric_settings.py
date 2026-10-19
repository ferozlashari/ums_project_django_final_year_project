from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_sitesettings_llm_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='biometric_attendance_enabled',
            field=models.BooleanField(default=True, verbose_name='Show fingerprint/face "Verify & Check In" option on attendance, exams, and online classes'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='require_biometric_attendance',
            field=models.BooleanField(default=False, verbose_name='Require biometric verification for attendance (hide plain self check-in)'),
        ),
    ]
