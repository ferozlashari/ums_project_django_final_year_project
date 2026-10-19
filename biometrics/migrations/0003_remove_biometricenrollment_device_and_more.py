# Removes physical-biometric-hardware support (BiometricDevice,
# BiometricEnrollment, BiometricPunch) - identity verification for
# attendance/exams/online classes is now WebAuthn/passkey-only.
# Simplified by hand from the autodetected version, which failed on
# SQLite due to field-removal/unique_together ordering: clear the
# unique_together constraint before touching the fields it covers.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('biometrics', '0002_alter_biometricpunch_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='examattendance',
            name='method',
            field=models.CharField(choices=[('webauthn', 'Passkey / Device Authentication'), ('manual', 'Manually Verified by Invigilator')], default='webauthn', max_length=20),
        ),
        migrations.AlterField(
            model_name='onlineclassattendance',
            name='method',
            field=models.CharField(choices=[('webauthn', 'Passkey / Device Authentication'), ('manual', 'Marked by Teacher')], default='webauthn', max_length=20),
        ),
        migrations.AlterUniqueTogether(
            name='biometricenrollment',
            unique_together=set(),
        ),
        migrations.DeleteModel(name='BiometricPunch'),
        migrations.DeleteModel(name='BiometricEnrollment'),
        migrations.DeleteModel(name='BiometricDevice'),
    ]
