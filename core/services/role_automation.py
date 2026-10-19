"""Role automation: one-click operations for teachers, results officers and students.

Everything here goes through the same rules the individual screens use:
  * a teacher only ever touches sections they are assigned to;
  * marks are entered as RAW marks per assessment component - totals, percentage
    and grade are always calculated, never typed;
  * a submitted/published result is locked for the teacher until an officer reopens it;
  * automation only does what a person could do by hand (it never invents attendance,
    marks or payments) and every run is recorded (AutomationRun + audit log).
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

DAY_CODES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


def _notify_once(user, title, message, key):
    from core.services.automation import AutomationService
    AutomationService._notify_once(user, title, message, key)


def _band(pct):
    from exams.grading import band_for
    return band_for(pct)


class TeacherAutomationService:
    # ---- scope ------------------------------------------------------------
    @staticmethod
    def sections_for(user):
        from academics.models import CourseSection
        from core.permissions import user_role, teaching_sections
        if user_role(user) == 'admin':
            return CourseSection.objects.select_related('course')
        return teaching_sections(user).select_related('course')

    @staticmethod
    def current_semester():
        from core.services.academic import AcademicEligibilityService
        return AcademicEligibilityService.current_semester()

    @classmethod
    def todays_sections(cls, user, on=None):
        """Sections the teacher is actually timetabled to teach on `on` (default today)."""
        from timetable.models import TimetableAssignment
        on = on or timezone.localdate()
        semester = cls.current_semester()
        slots = TimetableAssignment.objects.filter(status='approved', timeslot__day=DAY_CODES[on.weekday()])
        if semester:
            slots = slots.filter(Q(semester=semester) | Q(semester__isnull=True))
        return cls.sections_for(user).filter(pk__in=slots.values('section_id')).order_by('course__code', 'code')

    # ---- attendance ---------------------------------------------------------
    @classmethod
    def attendance_sheets(cls, user, day, section_ids=None, show_all=False, course_id=None):
        """Rosters for every class on `day`, with the state already saved (if any)."""
        from academics.models import CourseRegistration
        from attendance.models import AttendanceRecord, AttendanceSession
        semester = cls.current_semester()
        if semester is None:
            return semester, []
        sections = cls.sections_for(user) if show_all else cls.todays_sections(user, day)
        if section_ids:
            sections = sections.filter(pk__in=section_ids)
        if course_id:
            sections = sections.filter(course_id=course_id)
        sheets = []
        for section in sections:
            regs = list(CourseRegistration.objects.filter(section=section, status='registered', semester=semester)
                        .select_related('student').order_by('student__full_name'))
            saved = {r.student_id: r.present for r in
                     AttendanceRecord.objects.filter(section=section, date=day, semester=semester)}
            session = AttendanceSession.objects.filter(section=section, semester=semester, date=day).first()
            sheets.append({
                'section': section, 'semester': semester,
                'rows': [{'student': r.student, 'present': saved.get(r.student_id, True)} for r in regs],
                'already_marked': bool(saved),
                'locked': bool(session and not session.is_open),
                'session': session,
                'pending_request': bool(session and session.correction_requests.filter(status='pending').exists()),
            })
        return semester, sheets

    @classmethod
    def mark_all_present_where_unmarked(cls, user, day=None):
        """'Present-all' for every timetabled class today that has no attendance yet.
        Teacher-initiated, recorded as manual attendance by that teacher, and it never
        touches a class that already has attendance saved."""
        from attendance.models import AttendanceRecord
        from attendance.services import save_section_attendance, date_problem
        from academics.models import CourseRegistration
        day = day or timezone.localdate()
        semester = cls.current_semester()
        out = {'marked_sections': 0, 'marked_students': 0, 'skipped_sections': 0, 'problem': None}
        if semester is None:
            out['problem'] = 'No active semester is configured.'
            return out
        out['problem'] = date_problem(semester, day)
        if out['problem']:
            return out
        for section in cls.todays_sections(user, day):
            if AttendanceRecord.objects.filter(section=section, date=day, semester=semester).exists():
                out['skipped_sections'] += 1
                continue
            ids = list(CourseRegistration.objects.filter(section=section, status='registered', semester=semester)
                       .values_list('student_id', flat=True))
            if not ids:
                out['skipped_sections'] += 1
                continue
            out['marked_students'] += save_section_attendance(
                section, semester, day, ids, user, remark='Present-all (teacher automation)')
            out['marked_sections'] += 1
        return out

    # ---- marks -------------------------------------------------------------
    @staticmethod
    def scheme_for(course):
        from exams.models import AssessmentScheme
        return (AssessmentScheme.objects.filter(course=course, is_active=True)
                .prefetch_related('components').order_by('-version').first())

    @staticmethod
    def is_locked(registration):
        pub = getattr(registration, 'result_publication', None)
        return bool(pub and pub.status != 'reopened')

    @classmethod
    def marks_sheet(cls, section):
        """Students x components with current marks and the CALCULATED total/grade."""
        from academics.models import CourseRegistration
        from exams.models import AssessmentMark
        from exams.services_dynamic import DynamicAssessmentService
        scheme = cls.scheme_for(section.course)
        regs = list(CourseRegistration.objects.filter(section=section, status='registered')
                    .select_related('student', 'result_publication').order_by('student__full_name'))
        if scheme is None:
            return {'scheme': None, 'components': [], 'rows': []}
        components = list(scheme.components.all().order_by('order', 'id'))
        marks = {(m.registration_id, m.component_id): m.raw_marks
                 for m in AssessmentMark.objects.filter(registration__in=regs, component__in=components)}
        rows = []
        for reg in regs:
            calc = DynamicAssessmentService.calculate(reg, scheme)
            band = _band(calc['percentage'])
            pub = getattr(reg, 'result_publication', None)
            rows.append({
                'registration': reg, 'student': reg.student,
                'cells': [{'component': c, 'value': marks.get((reg.pk, c.pk))} for c in components],
                'total': calc['total'], 'complete': calc['complete'],
                'grade': band.grade if calc['complete'] else '', 'grade_point': band.grade_point if calc['complete'] else None,
                'status': pub.get_status_display() if pub else 'Not submitted',
                'locked': cls.is_locked(reg),
            })
        return {'scheme': scheme, 'components': components, 'rows': rows}

    @classmethod
    @transaction.atomic
    def save_marks(cls, user, section, posted, ignore_unknown=False):
        """`posted` maps 'mark_<registration_id>_<component_id>' -> text. Blank = leave unchanged."""
        from academics.models import CourseRegistration
        from exams.services_dynamic import DynamicAssessmentService
        scheme = cls.scheme_for(section.course)
        result = {'saved': 0, 'locked': 0, 'errors': []}
        if scheme is None:
            result['errors'].append('No assessment scheme has been defined for this course by administration.')
            return result
        comps = {c.pk: c for c in scheme.components.all()}
        regs = {r.pk: r for r in CourseRegistration.objects.filter(section=section, status='registered')
                .select_related('result_publication')}
        locked_seen = set()
        for key, raw in posted.items():
            if not key.startswith('mark_') or not str(raw).strip():
                continue
            try:
                _, rid, cid = key.split('_')
                reg, comp = regs[int(rid)], comps[int(cid)]
            except (ValueError, KeyError):
                if not ignore_unknown:
                    result['errors'].append(f'Ignored unknown entry {key!r}.')
                continue
            if cls.is_locked(reg):
                locked_seen.add(reg.pk)
                continue
            try:
                value = Decimal(str(raw).strip())
            except InvalidOperation:
                result['errors'].append(f'{reg.student.full_name} / {comp.name}: "{raw}" is not a number.')
                continue
            if value < 0 or value > comp.max_marks:
                result['errors'].append(f'{reg.student.full_name} / {comp.name}: {value} is outside 0-{comp.max_marks}.')
                continue
            DynamicAssessmentService.enter_mark(reg, comp, value, user=user)
            result['saved'] += 1
        result['locked'] = len(locked_seen)
        return result

    @classmethod
    @transaction.atomic
    def submit_complete_results(cls, user, section):
        """Submit every student whose required components are all entered. Others stay editable."""
        from exams.models import ResultPublication
        from exams.services_dynamic import DynamicAssessmentService, ResultPublicationService
        scheme = cls.scheme_for(section.course)
        out = {'submitted': 0, 'incomplete': 0, 'already': 0}
        if scheme is None:
            return out
        from academics.models import CourseRegistration
        for reg in CourseRegistration.objects.filter(section=section, status='registered').select_related('result_publication'):
            pub = getattr(reg, 'result_publication', None)
            if pub and pub.status != 'reopened':
                out['already'] += 1
                continue
            if not DynamicAssessmentService.calculate(reg, scheme)['complete']:
                out['incomplete'] += 1
                continue
            ResultPublicationService.advance(reg, 'teacher_submitted', user=user)   # also handles 'reopened'
            out['submitted'] += 1
        return out

    # ---- all classes at once ---------------------------------------------
    @classmethod
    def subjects_for(cls, user):
        from academics.models import Course
        return Course.objects.filter(sections__in=cls.sections_for(user)).distinct().order_by('code')

    @classmethod
    def filtered_sections(cls, user, course_id=None, section_id=None, teacher_id=None):
        """Sections the user may see, narrowed by the screen's filters. `teacher_id` only narrows
        (an administrator can pick a teacher; a teacher can only ever see their own anyway)."""
        sections = cls.sections_for(user)
        if course_id:
            sections = sections.filter(course_id=course_id)
        if section_id:
            sections = sections.filter(pk=section_id)
        if teacher_id:
            sections = sections.filter(instructor_id=teacher_id)
        return sections.select_related('course', 'instructor__user').order_by('course__code', 'code')

    @classmethod
    def attendance_summary(cls, user, semester=None, course_id=None, section_id=None, teacher_id=None,
                           date_from=None, date_to=None, below_only=False, q=''):
        """Per class and per student attendance totals for every class at once."""
        from django.db.models import Count, Q as DQ
        from academics.models import CourseRegistration
        from attendance.models import AttendanceRecord
        from core.models import SiteSettings
        semester = semester or cls.current_semester()
        minimum = float(SiteSettings.load().minimum_attendance_percent)
        q = (q or '').strip().lower()
        blocks, grand_total, grand_present = [], 0, 0
        if semester is None:
            return {'semester': None, 'minimum': minimum, 'blocks': [], 'totals': {}}
        for sec in cls.filtered_sections(user, course_id, section_id, teacher_id):
            recs = AttendanceRecord.objects.filter(section=sec, semester=semester)
            if date_from:
                recs = recs.filter(date__gte=date_from)
            if date_to:
                recs = recs.filter(date__lte=date_to)
            per = {r['student_id']: r for r in recs.values('student_id').annotate(
                total=Count('id'), present=Count('id', filter=DQ(present=True)))}
            regs = list(CourseRegistration.objects.filter(section=sec, status='registered', semester=semester)
                        .select_related('student').order_by('student__full_name'))
            rows = []
            for reg in regs:
                st = reg.student
                if q and q not in st.full_name.lower() and q not in (st.admission_no or '').lower():
                    continue
                t = per.get(st.pk)
                total, present = (t['total'], t['present']) if t else (0, 0)
                pct = round(present * 100 / total, 1) if total else None
                rows.append({'student': st, 'total': total, 'present': present, 'absent': total - present, 'pct': pct,
                             'low': pct is not None and pct < minimum})
            low = sum(1 for r in rows if r['low'])
            if below_only:
                rows = [r for r in rows if r['low']]
            sec_total = sum(r['total'] for r in rows)
            sec_present = sum(r['present'] for r in rows)
            grand_total += sec_total
            grand_present += sec_present
            blocks.append({
                'section': sec, 'sessions': recs.values('date').distinct().count(), 'students': len(regs),
                'shown': len(rows), 'rows': rows, 'low_count': low,
                'avg': round(sec_present * 100 / sec_total, 1) if sec_total else None,
            })
        return {'semester': semester, 'minimum': minimum, 'blocks': blocks,
                'totals': {'classes': len(blocks), 'students': sum(b['students'] for b in blocks),
                           'low': sum(b['low_count'] for b in blocks),
                           'avg': round(grand_present * 100 / grand_total, 1) if grand_total else None}}

    @classmethod
    def marks_blocks(cls, user, course_id=None, section_id=None, teacher_id=None, status='', q=''):
        """Marks sheets for every matching class at once. status: '' | incomplete | ready | submitted."""
        q = (q or '').strip().lower()
        blocks, skipped = [], []
        for sec in cls.filtered_sections(user, course_id, section_id, teacher_id):
            sheet = cls.marks_sheet(sec)
            if sheet['scheme'] is None:
                skipped.append(sec)
                continue
            rows = []
            for r in sheet['rows']:
                st = 'submitted' if r['locked'] else ('ready' if r['complete'] else 'incomplete')
                r['state'] = st
                if status and st != status:
                    continue
                if q and q not in r['student'].full_name.lower() and q not in (r['student'].admission_no or '').lower():
                    continue
                rows.append(r)
            if rows:
                blocks.append({'section': sec, 'sheet': {**sheet, 'rows': rows}, 'all_students': len(sheet['rows'])})
        return blocks, skipped

    @classmethod
    @transaction.atomic
    def save_marks_all(cls, user, posted):
        """Save marks for many classes in one request. Entries for classes the user does not teach are
        refused and reported, never applied."""
        from academics.models import CourseRegistration
        sections = [s for s in cls.sections_for(user) if cls.scheme_for(s.course) is not None]
        total = {'saved': 0, 'locked': 0, 'errors': []}
        for sec in sections:
            r = cls.save_marks(user, sec, posted, ignore_unknown=True)
            total['saved'] += r['saved']
            total['locked'] += r['locked']
            total['errors'] += r['errors']
        mine = set(CourseRegistration.objects.filter(section__in=sections).values_list('pk', flat=True))
        foreign = 0
        for key, raw in posted.items():
            if key.startswith('mark_') and str(raw).strip():
                try:
                    rid = int(key.split('_')[1])
                except (ValueError, IndexError):
                    foreign += 1
                    continue
                if rid not in mine:
                    foreign += 1
        if foreign:
            total['errors'].append(f'{foreign} entr{"y" if foreign == 1 else "ies"} for classes you do not teach (or without a scheme) were ignored.')
        return total

    @classmethod
    def submit_complete_results_all(cls, user, section_ids):
        out = {'submitted': 0, 'incomplete': 0, 'already': 0}
        allowed = {s.pk: s for s in cls.sections_for(user)}
        for sid in section_ids:
            if sid in allowed:
                r = cls.submit_complete_results(user, allowed[sid])
                for k in out:
                    out[k] += r[k]
        return out

    @classmethod
    def marks_overview(cls, user):
        rows = []
        for section in cls.sections_for(user):
            sheet = cls.marks_sheet(section)
            rows.append({
                'section': section, 'scheme': sheet['scheme'], 'students': len(sheet['rows']),
                'complete': sum(1 for r in sheet['rows'] if r['complete']),
                'submitted': sum(1 for r in sheet['rows'] if r['locked']),
            })
        return rows

    # ---- housekeeping ---------------------------------------------------------
    @classmethod
    def low_attendance_alerts(cls, user, dry_run=False):
        from academics.models import CourseRegistration
        from attendance.models import AttendanceRecord
        from core.models import SiteSettings
        semester = cls.current_semester()
        if semester is None:
            return {'low_attendance': 0}
        minimum = float(SiteSettings.load().minimum_attendance_percent)
        count = 0
        for section in cls.sections_for(user):
            for reg in CourseRegistration.objects.filter(section=section, status='registered', semester=semester).select_related('student__user'):
                recs = AttendanceRecord.objects.filter(student=reg.student, section=section, semester=semester)
                total = recs.count()
                if not total:
                    continue
                pct = recs.filter(present=True).count() * 100 / total
                if pct < minimum:
                    count += 1
                    if not dry_run:
                        _notify_once(reg.student.user, 'Low attendance warning',
                                     f'Your attendance in {section.course.code} is {pct:.1f}%. The minimum required is {minimum:g}%.',
                                     f'low-{section.pk}-{reg.student_id}')
        return {'low_attendance': count}

    @classmethod
    def assignment_reminders(cls, user, dry_run=False, hours=48):
        from academics.models import CourseRegistration
        from assignments.models import Assignment
        now = timezone.now()
        count = 0
        for a in Assignment.objects.filter(section__in=cls.sections_for(user), due_date__gte=now,
                                           due_date__lte=now + datetime.timedelta(hours=hours)).select_related('section__course'):
            submitted = set(a.submissions.values_list('student_id', flat=True))
            for reg in CourseRegistration.objects.filter(section=a.section, status='registered').select_related('student__user'):
                if reg.student_id in submitted:
                    continue
                count += 1
                if not dry_run:
                    _notify_once(reg.student.user, 'Assignment due soon',
                                 f'"{a.title}" ({a.section.course.code}) is due {a.due_date:%d %b %H:%M} and you have not submitted yet.',
                                 f'asg-{a.pk}-{reg.student_id}')
        return {'assignment_reminders': count}

    @classmethod
    def run_housekeeping(cls, user, dry_run=False):
        """Teacher's own 'run all updates' button. Recorded like any automation run."""
        from core.models import AutomationRun, AutomationTask, log_action
        run = AutomationRun.objects.create(trigger=f'teacher:{user.pk}', status='running', dry_run=dry_run, started_at=timezone.now())
        stats, failures = {}, 0
        for name, fn in (('low_attendance_alerts', cls.low_attendance_alerts), ('assignment_reminders', cls.assignment_reminders)):
            task = AutomationTask.objects.create(run=run, name=name, status='running', started_at=timezone.now(), attempts=1)
            try:
                result = fn(user, dry_run=dry_run)
                task.status, task.result = 'completed', result
                stats.update(result)
            except Exception as exc:  # noqa: BLE001 - recorded, others still run
                failures += 1
                task.status, task.error = 'failed', f'{type(exc).__name__}: {exc}'
            task.finished_at = timezone.now()
            task.save()
        run.status = 'completed' if not failures else ('failed' if failures == 2 else 'partial')
        run.finished_at, run.summary = timezone.now(), stats
        run.save()
        if not dry_run:
            log_action(user, 'AUTOMATION_RUN', obj='teacher housekeeping', changes={k: ['', str(v)] for k, v in stats.items()})
        return stats


class ResultWorkflowService:
    """Verify -> approve -> publish, each stage gated by its own governance permission."""
    STAGES = [  # (from, to, action needed, button label)
        ('teacher_submitted', 'department_verified', 'verify', 'Verify (department)'),
        ('department_verified', 'exam_verified', 'approve', 'Approve (exam office)'),
        ('exam_verified', 'published', 'publish', 'Publish'),
    ]

    @classmethod
    def stage_for(cls, status):
        return next((s for s in cls.STAGES if s[0] == status), None)

    @classmethod
    def may(cls, user, action, registration):
        """View is plain scope-aware access. Every decision action (verify,
        approve, publish, override) is *authority*: the System Administrator can
        only use it as a logged break-glass fallback when no office holder exists."""
        from governance.permissions import authority_perm, has_perm
        course = registration.section.course
        if action == 'view':
            return has_perm(user, 'results', action, program=course.program)
        return authority_perm(user, 'results', action, program=course.program)[0]

    @classmethod
    def _earlier_stage_by(cls, user, pub):
        """True if `user` already carried out an earlier stage for this same result."""
        from core.models import AuditLog
        return AuditLog.objects.filter(
            actor=user, object_repr=str(pub.registration),
            action__in=['RESULT_DEPARTMENT_VERIFIED', 'RESULT_EXAM_VERIFIED']).exists()

    @classmethod
    def queue(cls, user):
        """Publications this user may act on, with the action they can take."""
        from exams.models import ResultPublication
        items = []
        pubs = (ResultPublication.objects.exclude(status='published')
                .select_related('registration__student', 'registration__section__course__program')
                .order_by('registration__section__course__code', 'registration__student__full_name'))
        for pub in pubs:
            stage = cls.stage_for(pub.status)
            can_advance = bool(stage and cls.may(user, stage[2], pub.registration))
            can_reopen = cls.may(user, 'override', pub.registration) and pub.status != 'reopened'
            if can_advance or can_reopen or cls.may(user, 'view', pub.registration):
                items.append({'pub': pub, 'stage': stage, 'can_advance': can_advance, 'can_reopen': can_reopen})
        return items

    @classmethod
    @transaction.atomic
    def advance(cls, user, pub):
        from core.models import notify, log_action
        from exams.models import AssessmentMark
        from exams.services_dynamic import ResultPublicationService
        stage = cls.stage_for(pub.status)
        if not stage:
            raise ValueError('This result cannot be advanced from its current state.')
        if not cls.may(user, stage[2], pub.registration):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f'You need the "{stage[2]}" permission on Results for this program.')
        from governance.permissions import authority_perm
        glass = authority_perm(user, 'results', stage[2], program=pub.registration.section.course.program)[1]
        if not glass and cls._earlier_stage_by(user, pub):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('You already handled an earlier stage of this result - a different person must do this stage (separation of duties).')
        old = pub.status
        ResultPublicationService.advance(pub.registration, stage[1], user=user)
        if stage[1] == 'published':
            AssessmentMark.objects.filter(registration=pub.registration).update(published_at=timezone.now())
            notify(pub.registration.student.user, 'Result published',
                   f'Your result for {pub.registration.section.course.code} is now available.', level='info')
        log_action(user, 'RESULT_' + stage[1].upper(), obj=str(pub.registration), changes={'status': [old, stage[1]]},
                   reason='BREAK-GLASS: System Administrator acted because no office holder exists' if glass else '')
        return stage[1]

    @classmethod
    @transaction.atomic
    def reopen(cls, user, pub, reason):
        from core.models import log_action
        if not cls.may(user, 'override', pub.registration):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('You need the "override" permission on Results for this program.')
        if not reason.strip():
            raise ValueError('A reason is required to reopen a result.')
        from exams.services_dynamic import ResultPublicationService
        old = pub.status
        changes = {'status': [old, 'reopened']}
        if old == 'published':
            removed = ResultPublicationService.unsync_grade_entry(pub.registration)
            if removed:   # the published value is preserved in the audit trail, never silently lost
                changes['published_marks'] = [str(removed[0]), '']
                changes['published_grade'] = [removed[1], '']
        pub.status, pub.updated_by, pub.remarks = 'reopened', user, reason.strip()
        pub.published_at = None
        pub.save()
        log_action(user, 'RESULT_REOPENED', obj=str(pub.registration), changes=changes, reason=reason)


class StudentAutomationService:
    @classmethod
    def overview(cls, student):
        from academics.models import CourseRegistration
        from attendance.models import AttendanceRecord
        from core.models import SiteSettings
        from core.services.academic import AcademicEligibilityService as S
        from finance.models import Invoice
        semester = S.current_semester()
        recommended = list(S.recommended_courses(student, semester)) if semester else []
        registered_ids = set(CourseRegistration.objects.filter(student=student, semester=semester, status='registered')
                             .values_list('section__course_id', flat=True)) if semester else set()
        minimum = float(SiteSettings.load().minimum_attendance_percent)
        shortfalls = []
        if semester:
            for reg in CourseRegistration.objects.filter(student=student, semester=semester, status='registered').select_related('section__course'):
                recs = AttendanceRecord.objects.filter(student=student, section=reg.section, semester=semester)
                total = recs.count()
                if total:
                    pct = recs.filter(present=True).count() * 100 / total
                    if pct < minimum:
                        shortfalls.append({'course': reg.section.course, 'percent': round(pct, 1)})
        return {
            'semester': semester,
            'to_register': [i.course for i in recommended if i.course.pk not in registered_ids],
            'registered_count': len(registered_ids),
            'unpaid': list(Invoice.objects.filter(student=student, paid=False).order_by('due_date')[:5]),
            'has_semester_challan': bool(semester and Invoice.objects.filter(student=student, category='semester', semester=semester).exists()),
            'registration_closes': getattr(semester, 'registration_close', None),
            'shortfalls': shortfalls, 'minimum': minimum,
        }

    @classmethod
    def register_recommended(cls, student):
        from core.services.academic import AcademicEligibilityService as S
        result = S.auto_assign_current_courses(student)
        return {'registered': [getattr(c, 'section', c) for c in result['created']], 'skipped': result['skipped']}

    @classmethod
    def semester_challan(cls, student):
        from finance.services import FeeChallanService
        return FeeChallanService.generate_semester_fee(student)
