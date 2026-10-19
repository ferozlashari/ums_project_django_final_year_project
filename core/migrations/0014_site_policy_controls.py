from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('core','0013_sitesettings_gemini')]
    operations = [
        migrations.AddField(model_name='sitesettings', name='minimum_attendance_percent', field=models.DecimalField(decimal_places=2, default=80, max_digits=5)),
        migrations.AddField(model_name='sitesettings', name='max_registration_credits', field=models.PositiveSmallIntegerField(default=21)),
        migrations.AddField(model_name='sitesettings', name='max_retake_attempts', field=models.PositiveSmallIntegerField(default=2)),
        migrations.AddField(model_name='sitesettings', name='max_improvement_attempts', field=models.PositiveSmallIntegerField(default=1)),
        migrations.AddField(model_name='sitesettings', name='late_fee_percent', field=models.DecimalField(decimal_places=2, default=5, max_digits=5)),
    ]
