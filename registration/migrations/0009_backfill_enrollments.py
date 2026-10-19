from django.db import migrations


def backfill(apps, schema_editor):
    Student = apps.get_model('registration', 'Student')
    Enrollment = apps.get_model('registration', 'Enrollment')
    Curriculum = apps.get_model('academics', 'Curriculum')
    for student in Student.objects.filter(program__isnull=False).exclude(enrollments__status='active'):
        curriculum = (Curriculum.objects.filter(program_id=student.program_id, is_active=True)
                     .order_by('-version').first())
        started = (student.admission_semester.start_date if student.admission_semester_id
                  else student.user.date_joined.date())
        Enrollment.objects.create(student=student, program_id=student.program_id, curriculum=curriculum,
                                  status='active', started_on=started)


def noop(apps, schema_editor):
    pass  # Enrollment rows are historical audit data - not reversed.


class Migration(migrations.Migration):
    dependencies = [('registration', '0008_enrollment_backbone')]
    operations = [migrations.RunPython(backfill, noop)]
