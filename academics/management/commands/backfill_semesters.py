from django.core.management.base import BaseCommand
from django.db.models import Q

from academics.models import CourseRegistration, Semester
from onlineclass.models import OnlineClass


def semester_for(day):
    """Semester whose dates contain `day`, else the most recent one before it."""
    covering = Semester.objects.filter(start_date__lte=day, end_date__gte=day).order_by('-start_date').first()
    return covering or Semester.objects.filter(end_date__lt=day).order_by('-end_date').first()


class Command(BaseCommand):
    help = ('Give legacy course registrations and online classes that have no semester the semester '
            'their date falls in. Dry-run by default; pass --apply to save. Rows that cannot be matched are listed, never guessed.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        apply = options['apply']
        fixed = unmatched = 0
        for reg in CourseRegistration.objects.filter(semester__isnull=True):
            sem = semester_for(reg.registered_at.date())
            if sem is None:
                unmatched += 1
                self.stdout.write(f'UNMATCHED registration #{reg.pk} ({reg.student} / {reg.section})')
                continue
            fixed += 1
            if apply:
                reg.semester = sem
                reg.save(update_fields=['semester'])
        for oc in OnlineClass.objects.filter(semester__isnull=True):
            sem = semester_for(oc.scheduled_at.date())
            if sem is None:
                unmatched += 1
                self.stdout.write(f'UNMATCHED online class #{oc.pk} ({oc.title})')
                continue
            fixed += 1
            if apply:
                oc.semester = sem
                oc.save(update_fields=['semester'])
        mode = 'APPLIED' if apply else 'DRY RUN (nothing saved - re-run with --apply)'
        self.stdout.write(self.style.SUCCESS(f'{mode}: {fixed} row(s) matched, {unmatched} unmatched.'))
