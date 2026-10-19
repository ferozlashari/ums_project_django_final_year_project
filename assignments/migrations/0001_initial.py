import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('academics', '0004_courseregistration'),
        ('registration', '0003_student_address_student_cnic_student_phone'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Assignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('due_date', models.DateTimeField()),
                ('max_marks', models.DecimalField(decimal_places=2, default=100, max_digits=6)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='academics.coursesection')),
            ],
            options={'ordering': ['-due_date']},
        ),
        migrations.CreateModel(
            name='Submission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text_answer', models.TextField(blank=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='assignment_submissions/%Y/%m/')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('marks_obtained', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('feedback', models.TextField(blank=True)),
                ('graded_at', models.DateTimeField(blank=True, null=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='assignments.assignment')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignment_submissions', to='registration.student')),
            ],
            options={'ordering': ['-submitted_at']},
        ),
        migrations.AlterUniqueTogether(
            name='submission',
            unique_together={('assignment', 'student')},
        ),
    ]
