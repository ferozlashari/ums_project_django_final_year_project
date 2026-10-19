"""Early-warning scoring combining attendance, assessment performance
(which itself already rolls up assignment/quiz/midterm/final marks - see
GradeEntry's component fields and .percentage), failed-course history,
and outstanding fees into one explainable risk level.

Kept as one shared function so the nightly/manual management command and
the in-app "Recalculate Now" button can never drift apart.
"""

ATTENDANCE_MEDIUM = 75.0
ATTENDANCE_HIGH = 60.0
GRADE_MEDIUM = 50.0
GRADE_HIGH = 40.0
FAILED_COURSES_MEDIUM = 1
FAILED_COURSES_HIGH = 2


def _bump(level, new_level):
    """Risk level only ever escalates (low -> medium -> high), never
    downgrades from one factor because another factor looked fine."""
    order = {'low': 0, 'medium': 1, 'high': 2}
    return new_level if order[new_level] > order[level] else level


def recalculate_risk_flags():
    """Recompute a RiskFlag for every active student, notify their
    department's faculty + admins the first time a student turns high-risk,
    and return a summary dict. Never raises - a scoring hiccup for one
    student must not stop the rest from being scored."""
    from registration.models import Student
    from attendance.models import AttendanceRecord
    from exams.models import GradeEntry
    from finance.models import Invoice
    from .models import RiskFlag
    from core.models import notify_many

    flagged_high = []
    scanned = 0

    for student in Student.objects.filter(status='active').select_related('program', 'program__department'):
        try:
            scanned += 1
            total = AttendanceRecord.objects.filter(student=student).count()
            present = AttendanceRecord.objects.filter(student=student, present=True).count()
            attendance_pct = round((present / total) * 100, 1) if total else None

            # `percentage` is a Python property, not a database column, so it
            # cannot be aggregated with Avg() in SQL - average it in Python.
            #
            # One query serves both this average AND the failed-courses
            # check below - ordered by entered_at so "latest attempt per
            # course" (next block) is correct.
            grade_entries = list(
                GradeEntry.objects.filter(student=student).select_related('exam__course').order_by('entered_at')
            )
            average_percentage = round(sum(g.percentage for g in grade_entries) / len(grade_entries), 1) if grade_entries else None

            # Distinct failed courses on the student's LATEST attempt only -
            # a course they later passed via retake/improvement shouldn't
            # keep counting against them forever.
            latest_by_course = {g.exam.course_id: g for g in grade_entries}
            failed_courses_count = sum(1 for g in latest_by_course.values() if g.status == 'fail')

            has_outstanding_fees = Invoice.objects.filter(student=student, paid=False).exists()

            reasons = []
            level = 'low'
            if attendance_pct is not None:
                if attendance_pct < ATTENDANCE_HIGH:
                    level = _bump(level, 'high')
                    reasons.append(f'Attendance is {attendance_pct}% (below {ATTENDANCE_HIGH}%).')
                elif attendance_pct < ATTENDANCE_MEDIUM:
                    level = _bump(level, 'medium')
                    reasons.append(f'Attendance is {attendance_pct}% (below {ATTENDANCE_MEDIUM}%).')
            if average_percentage is not None:
                if average_percentage < GRADE_HIGH:
                    level = _bump(level, 'high')
                    reasons.append(f'Average assessment score is {average_percentage}% (below {GRADE_HIGH}%).')
                elif average_percentage < GRADE_MEDIUM:
                    level = _bump(level, 'medium')
                    reasons.append(f'Average assessment score is {average_percentage}% (below {GRADE_MEDIUM}%).')
            if failed_courses_count >= FAILED_COURSES_HIGH:
                level = _bump(level, 'high')
                reasons.append(f'{failed_courses_count} courses currently have a failing grade.')
            elif failed_courses_count >= FAILED_COURSES_MEDIUM:
                level = _bump(level, 'medium')
                reasons.append(f'{failed_courses_count} course currently has a failing grade.')
            if has_outstanding_fees:
                # A financial hold alone is a real, immediate risk to
                # continued enrollment (unpaid fees block exam eligibility
                # elsewhere in the system) - always at least medium.
                level = _bump(level, 'medium')
                reasons.append('Has an outstanding (unpaid) fee challan.')

            if not reasons:
                # No risk signal - clear any stale flag rather than leaving it dangling.
                RiskFlag.objects.filter(student=student).delete()
                continue

            flag, created = RiskFlag.objects.update_or_create(
                student=student,
                defaults={
                    'level': level, 'attendance_pct': attendance_pct,
                    'average_percentage': average_percentage,
                    'failed_courses_count': failed_courses_count,
                    'has_outstanding_fees': has_outstanding_fees,
                    'reasons': '\n'.join(reasons),
                },
            )
            if level == 'high' and (created or flag.is_resolved):
                flag.is_resolved = False
                flag.save(update_fields=['is_resolved'])
                flagged_high.append(flag)

                advisors = []
                _prog = student.active_program
                dept = _prog.department if _prog else None
                if dept is not None:
                    from hr.models import Staff
                    advisors = [s.user for s in Staff.objects.filter(department=dept) if s.user_id]
                if advisors:
                    notify_many(
                        advisors, f'Early-warning: {student.full_name} is at high risk',
                        '\n'.join(reasons), level='danger', url='/risk/dashboard/',
                    )
        except Exception:
            continue

    return {'scanned': scanned, 'newly_high_risk': len(flagged_high)}
