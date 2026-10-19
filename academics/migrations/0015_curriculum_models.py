from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('academics', '0014_alter_coursesection_options_alter_faculty_options')]

    operations = [
        migrations.CreateModel(
            name='Curriculum',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('version', models.CharField(default='2026', max_length=40)),
                ('effective_from', models.DateField(blank=True, null=True)),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('total_credits', models.PositiveSmallIntegerField(default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='curricula', to='academics.program')),
            ],
            options={'ordering': ['program', '-version']},
        ),
        migrations.CreateModel(
            name='CurriculumSemester',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('semester_number', models.PositiveSmallIntegerField()),
                ('title', models.CharField(blank=True, max_length=120)),
                ('credits_required', models.PositiveSmallIntegerField(default=0)),
                ('curriculum', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='semesters', to='academics.curriculum')),
            ],
            options={'ordering': ['curriculum', 'semester_number']},
        ),
        migrations.CreateModel(
            name='CurriculumCourse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('course_type', models.CharField(choices=[('required', 'Required'), ('elective', 'Elective')], default='required', max_length=20)),
                ('elective_group', models.CharField(blank=True, max_length=100)),
                ('recommended', models.BooleanField(default=True)),
                ('minimum_grade', models.CharField(blank=True, max_length=5)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='curriculum_entries', to='academics.course')),
                ('curriculum_semester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='courses', to='academics.curriculumsemester')),
            ],
            options={'ordering': ['curriculum_semester__semester_number', 'course__code']},
        ),
        migrations.AddConstraint(
            model_name='curriculum',
            constraint=models.UniqueConstraint(fields=('program', 'version'), name='uniq_curriculum_program_version'),
        ),
        migrations.AddConstraint(
            model_name='curriculumsemester',
            constraint=models.UniqueConstraint(fields=('curriculum', 'semester_number'), name='uniq_curriculum_semester_number'),
        ),
        migrations.AddConstraint(
            model_name='curriculumcourse',
            constraint=models.UniqueConstraint(fields=('curriculum_semester', 'course'), name='uniq_curriculum_course'),
        ),
    ]
