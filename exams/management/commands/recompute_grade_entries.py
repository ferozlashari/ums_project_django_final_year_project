from django.core.management.base import BaseCommand

from exams.models import GradeEntry


class Command(BaseCommand):
    """Finds GradeEntry rows whose stored `marks`/`grade` no longer match
    what GradeEntry.save() would compute today, and (with --apply) fixes
    them by resaving.

    Why this is needed: `marks` is derived from the component fields at
    save() time. Older code paths (before validators/clamping existed)
    could leave a bad value on disk - e.g. a `marks` of 412 on a 100-mark
    exam - that a later bug fix stopped happening for NEW saves, but
    never touched already-stored rows. Resaving forces today's clamping
    and grade logic onto the stored data.

    Only rows that actually have a component breakdown are touched -
    a plain single-figure GradeEntry (no attendance/assignment/midterm/
    final set) is left exactly as entered, since there is nothing to
    recompute from.

    Defaults to a dry run: it only reports what WOULD change. Pass
    --apply to actually save the fixes.
    """
    help = 'Find (and optionally fix) GradeEntry rows whose stored marks/grade are stale relative to their component marks.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually resave the affected rows. Without this flag, only reports what would change.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        entries = GradeEntry.objects.select_related('student', 'exam', 'exam__course').all()

        changed = []
        for entry in entries:
            has_components = any(
                getattr(entry, f) is not None
                for f in ('attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks')
            )
            if not has_components:
                continue

            before = {
                'marks': entry.marks, 'grade': entry.grade,
                'attendance_marks': entry.attendance_marks, 'assignment_marks': entry.assignment_marks,
                'midterm_marks': entry.midterm_marks, 'final_marks': entry.final_marks,
            }
            # Recompute on a fresh copy so we can compare before deciding
            # whether to touch the real row.
            probe = GradeEntry.objects.get(pk=entry.pk)
            probe.save()
            after = {
                'marks': probe.marks, 'grade': probe.grade,
                'attendance_marks': probe.attendance_marks, 'assignment_marks': probe.assignment_marks,
                'midterm_marks': probe.midterm_marks, 'final_marks': probe.final_marks,
            }
            if before != after:
                changed.append((entry, before, after))
                if not apply_changes:
                    # We already saved `probe` above to compute `after`,
                    # which is the same DB row - roll it back to `before`
                    # since this is a dry run.
                    for field, value in before.items():
                        setattr(probe, field, value)
                    # Bypass save()'s own recompute so the rollback isn't
                    # immediately recomputed right back to `after`.
                    GradeEntry.objects.filter(pk=probe.pk).update(**before)

        if not changed:
            self.stdout.write(self.style.SUCCESS('No stale GradeEntry rows found - everything matches what save() computes today.'))
            return

        if apply_changes:
            from core.models import log_action
            for entry, before, after in changed:
                log_action(
                    actor=None, action='GRADE_RECOMPUTED', obj=entry,
                    changes={k: [str(before[k]), str(after[k])] for k in before if before[k] != after[k]},
                    reason='recompute_grade_entries management command - stale marks/grade fixed to match current save() logic.',
                )

        self.stdout.write(f'{"Fixed" if apply_changes else "Would fix"} {len(changed)} row(s):')
        for entry, before, after in changed:
            course_code = entry.exam.course.code if entry.exam and entry.exam.course else '?'
            self.stdout.write(
                f'  #{entry.pk} {entry.student} - {course_code}: '
                f'marks {before["marks"]} -> {after["marks"]}, grade {before["grade"] or "(none)"} -> {after["grade"]}'
            )
        if not apply_changes:
            self.stdout.write(self.style.WARNING('\nDry run only - nothing was changed. Re-run with --apply to save these fixes.'))
