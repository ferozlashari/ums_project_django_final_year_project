import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('registration', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RiskFlag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], default='low', max_length=10)),
                ('attendance_pct', models.FloatField(blank=True, null=True)),
                ('average_percentage', models.FloatField(blank=True, null=True)),
                ('reasons', models.TextField(blank=True, help_text='Human-readable reasons this student was flagged.')),
                ('is_resolved', models.BooleanField(default=False, help_text='Advisor has reviewed/handled this flag.')),
                ('first_flagged_at', models.DateTimeField(auto_now_add=True)),
                ('last_computed_at', models.DateTimeField(auto_now=True)),
                ('student', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='risk_flag', to='registration.student')),
            ],
            options={'ordering': ['-level', '-last_computed_at']},
        ),
    ]
