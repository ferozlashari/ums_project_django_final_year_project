from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_biometric_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='max_login_attempts',
            field=models.PositiveSmallIntegerField(default=5, verbose_name='Max failed login attempts before temporary lockout'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='login_lockout_minutes',
            field=models.PositiveSmallIntegerField(default=5, verbose_name='Lockout duration (minutes) after too many failed logins'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='require_2fa_for_admin',
            field=models.BooleanField(default=False, verbose_name='Require fingerprint/face 2FA for all admin accounts (blocks admin login without a registered device)'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='session_timeout_minutes',
            field=models.PositiveIntegerField(default=480, verbose_name='Auto-logout after this many minutes of inactivity (default 480 = 8 hours)'),
        ),
    ]
