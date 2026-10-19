import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('registration', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AlumniProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('graduation_year', models.PositiveIntegerField()),
                ('current_employer', models.CharField(blank=True, max_length=150)),
                ('job_title', models.CharField(blank=True, max_length=150)),
                ('industry', models.CharField(blank=True, max_length=100)),
                ('city', models.CharField(blank=True, max_length=100)),
                ('country', models.CharField(blank=True, default='Pakistan', max_length=100)),
                ('linkedin_url', models.URLField(blank=True)),
                ('bio', models.TextField(blank=True, help_text='A short note for the directory - career path, advice, what you studied.')),
                ('willing_to_mentor', models.BooleanField(default=False, help_text='Show a "Request mentorship" button to current students.')),
                ('is_public', models.BooleanField(default=True, help_text='Show this profile in the alumni directory. Turn off to stay listed only to admin.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('student', models.OneToOneField(help_text='Must be a graduated student record.', on_delete=django.db.models.deletion.CASCADE, related_name='alumni_profile', to='registration.student')),
            ],
            options={
                'ordering': ['-graduation_year', 'student__full_name'],
            },
        ),
        migrations.CreateModel(
            name='MentorshipRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(max_length=800)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('alumni', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentorship_requests', to='alumni.alumniprofile')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mentorship_requests_sent', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
