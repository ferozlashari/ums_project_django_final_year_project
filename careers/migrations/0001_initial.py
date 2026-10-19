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
            name='Employer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('website', models.URLField(blank=True)),
                ('industry', models.CharField(blank=True, max_length=100)),
                ('description', models.TextField(blank=True)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('added_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='JobPosting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('posting_type', models.CharField(choices=[('job', 'Full-time Job'), ('internship', 'Internship'), ('part_time', 'Part-time')], default='job', max_length=20)),
                ('description', models.TextField()),
                ('relevant_majors', models.CharField(blank=True, help_text='Comma-separated majors/programs this role suits, e.g. "Computer Science, IT"', max_length=300)),
                ('location', models.CharField(blank=True, max_length=150)),
                ('application_deadline', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('posted_at', models.DateTimeField(auto_now_add=True)),
                ('employer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='postings', to='careers.employer')),
                ('posted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-posted_at']},
        ),
        migrations.CreateModel(
            name='JobApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cover_note', models.TextField(blank=True, max_length=1500)),
                ('status', models.CharField(choices=[('submitted', 'Submitted'), ('shortlisted', 'Shortlisted'), ('rejected', 'Rejected'), ('hired', 'Hired')], default='submitted', max_length=20)),
                ('applied_at', models.DateTimeField(auto_now_add=True)),
                ('posting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='applications', to='careers.jobposting')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_applications', to='registration.student')),
            ],
            options={'ordering': ['-applied_at']},
        ),
        migrations.AlterUniqueTogether(
            name='jobapplication',
            unique_together={('posting', 'student')},
        ),
        migrations.CreateModel(
            name='ResumeProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('headline', models.CharField(blank=True, help_text='e.g. "Final-year CS student, backend focus"', max_length=200)),
                ('summary', models.TextField(blank=True)),
                ('skills', models.CharField(blank=True, help_text='Comma-separated, e.g. "Python, Django, SQL"', max_length=500)),
                ('experience', models.TextField(blank=True, help_text='Internships, projects, part-time work - one per line')),
                ('education_notes', models.TextField(blank=True)),
                ('links', models.CharField(blank=True, help_text='LinkedIn/GitHub/portfolio URLs, comma-separated', max_length=500)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('student', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='resume_profile', to='registration.student')),
            ],
        ),
    ]
