from django.core.management.base import BaseCommand
from registration.models import Student
from core.services.academic import AcademicEligibilityService


class Command(BaseCommand):
    help = 'Automatically recommend/register eligible curriculum courses for active students in the current semester.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        totals = {'students': 0, 'created': 0, 'skipped': 0}
        for student in Student.objects.filter(status='active').select_related('program', 'admission_semester'):
            result = AcademicEligibilityService.auto_assign_current_courses(student, dry_run=dry)
            totals['students'] += 1
            totals['created'] += len(result['created'])
            totals['skipped'] += len(result['skipped'])
        mode = 'DRY RUN' if dry else 'LIVE'
        self.stdout.write(self.style.SUCCESS(f'{mode}: students={totals["students"]}, registrations={totals["created"]}, skipped={totals["skipped"]}'))
