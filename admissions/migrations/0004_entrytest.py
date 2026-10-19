import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0003_application_cnic'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EntryTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('roll_number', models.CharField(max_length=40, unique=True)),
                ('test_date', models.DateField()),
                ('test_time', models.TimeField(blank=True, null=True)),
                ('venue', models.CharField(blank=True, default='Main Campus Examination Hall', max_length=200)),
                ('scheduled_at', models.DateTimeField(auto_now_add=True)),
                ('marks_obtained', models.DecimalField(blank=True, decimal_places=2, help_text='Out of 100.', max_digits=5, null=True)),
                ('evaluated_at', models.DateTimeField(blank=True, null=True)),
                ('application', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='entry_test', to='admissions.application')),
                ('scheduled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('evaluated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-scheduled_at']},
        ),
    ]
