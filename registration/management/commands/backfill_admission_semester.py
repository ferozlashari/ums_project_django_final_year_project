from django.core.management.base import BaseCommand

from registration.models import Student
from academics.models import Semester


class Command(BaseCommand):
    """Fills in Student.admission_semester for existing students who don't
    have one set - which is every student created before that field
    existed (see current_academic_position on Student, and an earlier
    session notes). Without it, "what year/semester of their degree is
    this student in" can't be computed at all for them.

    There is no reliably-recorded "date this student was admitted" for
    older records (the Enrollment model that should track this was never
    actually used anywhere in the app), so this uses the best real proxy
    available: the student's User account creation date
    (`user.date_joined`), matched against whichever Semester's date range
    contains it. This is a best-effort inference, not a certainty - it is
    wrong for any student whose account was created well after (or
    before) their actual admission, e.g. from a bulk import done long
    after the fact. That's exactly why this defaults to a dry run: review
    the proposed matches, and use --apply only once they look right.
    An admin can always correct an individual student's admission
    semester by hand afterwards from the student edit page.
    """
    help = 'Backfill Student.admission_semester for existing students (dry-run by default; --apply to commit).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually save the inferred admission_semester. Without this flag, only reports what would be set.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        semesters = list(Semester.objects.select_related('session').order_by('start_date'))
        if not semesters:
            self.stdout.write(self.style.WARNING('No Semester records exist yet - nothing to match students against.'))
            return

        students = Student.objects.filter(admission_semester__isnull=True).select_related('user', 'program')
        matched, unmatched = [], []

        for student in students:
            joined = student.user.date_joined.date() if student.user else None
            if joined is None:
                unmatched.append((student, 'No linked user account.'))
                continue

            # Prefer a semester whose date range actually contains the
            # join date; otherwise fall back to the most recent semester
            # that had already started by then (closest reasonable guess
            # for an account created slightly after enrollment opened).
            match = next((s for s in semesters if s.start_date <= joined <= s.end_date), None)
            if match is None:
                started_by_then = [s for s in semesters if s.start_date <= joined]
                match = started_by_then[-1] if started_by_then else None

            if match is None:
                unmatched.append((student, f'No semester found covering or before {joined} (account created before any recorded semester).'))
            else:
                matched.append((student, match))
                if apply_changes:
                    student.admission_semester = match
                    student.save(update_fields=['admission_semester'])

        if not matched and not unmatched:
            self.stdout.write(self.style.SUCCESS('Every student already has an admission_semester set - nothing to do.'))
            return

        self.stdout.write(f'{"Set" if apply_changes else "Would set"} admission_semester for {len(matched)} student(s):')
        for student, semester in matched:
            self.stdout.write(f'  {student.admission_no} - {student.full_name}: {semester.name} ({semester.session.year})')

        if unmatched:
            self.stdout.write(self.style.WARNING(f'\n{len(unmatched)} student(s) could not be matched:'))
            for student, reason in unmatched:
                self.stdout.write(f'  {student.admission_no} - {student.full_name}: {reason}')

        if not apply_changes:
            self.stdout.write(self.style.WARNING('\nDry run only - nothing was saved. Review the matches above, then re-run with --apply.'))
