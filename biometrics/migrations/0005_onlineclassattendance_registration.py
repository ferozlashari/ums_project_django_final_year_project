from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('biometrics', '0004_provider_events'),
        ('academics', '0014_alter_coursesection_options_alter_faculty_options'),
    ]
    operations = [
        migrations.AddField(
            model_name='onlineclassattendance',
            name='registration',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='online_attendance', to='academics.courseregistration'),
        ),
    ]
