from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """Every student with a program must have exactly one active Enrollment,
    because Enrollment (not Student.program) is now the academic source of truth."""
    Student = apps.get_model('registration', 'Student')
    Enrollment = apps.get_model('registration', 'Enrollment')
    Curriculum = apps.get_model('academics', 'Curriculum')
    today = timezone.localdate()
    active = set(Enrollment.objects.filter(status='active').values_list('student_id', flat=True))
    for s in Student.objects.filter(program__isnull=False).exclude(pk__in=active):
        cur = Curriculum.objects.filter(program_id=s.program_id, is_active=True).order_by('-version').first()
        Enrollment.objects.create(student_id=s.pk, program_id=s.program_id, curriculum=cur, status='active', started_on=today)


class Migration(migrations.Migration):
    dependencies = [('registration', '0010_alter_enrollment_options'), ('academics', '0001_initial')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
