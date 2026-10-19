import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Replaces the unused `Enrollment` model from 0001_initial (fields
    session_year/enrolled_at, never written to by any view or service -
    verified by search) with the real, wired-in Enrollment model: one
    active enrollment per student, program + pinned curriculum, and a
    status/date history. Safe as a drop-and-recreate because nothing in
    the codebase has ever created a row in the old table."""

    dependencies = [
        ('academics', '0015_curriculum_models'),
        ('registration', '0007_student_admission_semester'),
    ]

    operations = [
        migrations.DeleteModel(name='Enrollment'),
        migrations.CreateModel(
            name='Enrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('active', 'Active'), ('completed', 'Completed'),
                                                     ('transferred', 'Transferred'), ('withdrawn', 'Withdrawn')],
                                            default='active', max_length=15)),
                ('started_on', models.DateField()),
                ('ended_on', models.DateField(blank=True, null=True)),
                ('curriculum', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name='enrollments', to='academics.curriculum')),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='enrollments', to='academics.program')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='enrollments', to='registration.student')),
            ],
            options={'ordering': ['-started_on', '-id']},
        ),
        migrations.AddConstraint(
            model_name='enrollment',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status', 'active')), fields=('student',),
                name='uniq_one_active_enrollment_per_student'),
        ),
    ]
