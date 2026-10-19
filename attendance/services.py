"""Single save path for taking a section's attendance.

Used by the one-section bulk screen and the teacher's all-classes-today sheet,
so both enforce the same rules: only registered students of that section and
semester, idempotent per (student, section, date), and a locked (closed)
session cannot be silently edited by the teacher.
"""
import datetime as _dt

from django.db import transaction
from django.utils import timezone

from .models import AttendanceRecord, AttendanceSession


class AttendanceLocked(Exception):
    """The day's attendance for this section was finalised and is closed."""


def date_problem(semester, day):
    if day > timezone.localdate():
        return 'Attendance cannot be recorded for a future date.'
    if not (semester.start_date <= day <= semester.end_date):
        return (f'{day:%d %b %Y} is outside {semester.display_name} '
                f'({semester.start_date:%d %b} - {semester.end_date:%d %b %Y}).')
    return None


@transaction.atomic
def save_section_attendance(section, semester, day, present_student_ids, user,
                            allow_locked=False, lock=False, remark=''):
    """Record attendance for every registered student of `section`.

    `present_student_ids` = ids who are present; every other registered student
    is recorded absent. Returns the number of students saved. Raises
    AttendanceLocked if the session is closed and `allow_locked` is False.
    With lock=True the session is closed afterwards (teacher "finalise").
    """
    from academics.models import CourseRegistration
    session, _ = AttendanceSession.objects.get_or_create(
        section=section, semester=semester, date=day,
        defaults={'created_by': user, 'started_at': timezone.now(), 'attendance_type': 'physical'},
    )
    if not session.is_open and not allow_locked:
        raise AttendanceLocked(f'{section} on {day:%d %b %Y} is finalised.')
    present = set(present_student_ids)
    saved = 0
    regs = (CourseRegistration.objects.filter(section=section, status='registered', semester=semester)
            .select_related('student'))
    for reg in regs:
        is_present = reg.student_id in present
        record, created = AttendanceRecord.objects.get_or_create(
            student=reg.student, section=section, date=day,
            defaults={'present': is_present, 'method': 'manual', 'recorded_by': user, 'semester': semester,
                      'session': session, 'registration': reg, 'remarks': remark},
        )
        if not created and record.present != is_present:
            record.present, record.method, record.recorded_by = is_present, 'manual', user
            record.semester, record.session, record.registration = semester, session, reg
            record.save(update_fields=['present', 'method', 'recorded_by', 'semester', 'session', 'registration'])
        saved += 1
    if lock:
        session.is_open = False
        session.ended_at = timezone.now()
        session.save(update_fields=['is_open', 'ended_at'])
    return saved


# ---- correction workflow ---------------------------------------------------
def may_decide_corrections(user, program=None):
    from core.permissions import user_role
    from governance.permissions import has_perm
    return user_role(user) == 'admin' or has_perm(user, 'attendance', 'approve', program=program)


@transaction.atomic
def request_correction(user, session, reason):
    from .models import AttendanceCorrectionRequest
    if session.is_open:
        raise ValueError('This attendance sheet is not finalised - you can edit it directly.')
    if not reason.strip():
        raise ValueError('A reason is required.')
    if session.correction_requests.filter(status='pending').exists():
        raise ValueError('A correction request for this sheet is already pending.')
    return AttendanceCorrectionRequest.objects.create(session=session, requested_by=user, reason=reason.strip())


@transaction.atomic
def decide_correction(user, req, approve, note=''):
    from django.core.exceptions import PermissionDenied
    from core.models import log_action, notify
    if req.status != 'pending':
        raise ValueError('This request has already been decided.')
    if not may_decide_corrections(user, program=req.session.section.course.program):
        raise PermissionDenied('You need the Attendance "approve" permission for this program.')
    if not approve and not note.strip():
        raise ValueError('A note is required when rejecting a request.')
    req.status = 'approved' if approve else 'rejected'
    req.decided_by, req.decided_at, req.decision_note = user, timezone.now(), note.strip()
    req.save()
    if approve:
        req.session.is_open, req.session.ended_at = True, None
        req.session.save(update_fields=['is_open', 'ended_at'])
    log_action(user, 'ATTENDANCE_CORRECTION_' + req.status.upper(), obj=str(req.session),
               changes={'reason': ['', req.reason]}, reason=note)
    notify(req.requested_by, f'Attendance correction {req.status}',
           f'{req.session.section.course.code} on {req.session.date:%d %b %Y}: ' +
           ('the sheet is open for editing again.' if approve else (note or 'rejected.')), level='info')
    return req
