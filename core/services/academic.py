from dataclasses import dataclass
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from academics.models import CourseRegistration, CourseSection, Semester
from exams.models import GradeEntry
from registration.models import Student
from core.models import SiteSettings


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...] = ()


class AcademicEligibilityService:
    """Deterministic source for current semester and registration rules."""

    @staticmethod
    def current_semester():
        today = timezone.localdate()
        return (Semester.objects.filter(start_date__lte=today, end_date__gte=today)
                .select_related('session').order_by('-start_date').first())

    @staticmethod
    def passed_course_ids(student):
        entries = GradeEntry.objects.filter(student=student).select_related('exam__course')
        return {entry.exam.course_id for entry in entries if entry.status == 'pass'}

    @classmethod
    def completed_course_ids(cls, student):
        return cls.passed_course_ids(student)

    @classmethod
    def academic_position(cls, student, current_semester=None):
        """Compute position from curriculum + completed credits, not elapsed time alone.

        For a standard lockstep curriculum, the highest curriculum semester whose
        prerequisites/required credits are satisfied is the student's completed
        position. The next semester is the registration target. If no curriculum
        exists, admission-semester arithmetic remains a safe compatibility fallback.
        """
        if not student or not student.active_program_id:
            return None
        current_semester = current_semester or cls.current_semester()
        # Single source of truth: the student's PINNED curriculum (via their
        # current Enrollment), not whatever curriculum happens to be marked
        # active right now - otherwise this position calc and every other
        # curriculum-aware decision (recommendations, eligibility) could
        # silently disagree the moment an admin activates a new version.
        curriculum = cls.active_curriculum(student)
        if not curriculum:
            admission = getattr(student, 'admission_semester', None)
            if not admission or admission.semester_number is None or not current_semester or current_semester.semester_number is None:
                return None
            target = current_semester.semester_number - admission.semester_number + 1
            total = (student.active_program.duration_years or 4) * 2
            if target < 1:
                return None
            target = min(target, total)
            return {'year': (target + 1)//2, 'semester': target, 'total_semesters': total,
                    'completed_semesters': max(0, target - 1), 'source': 'admission-cohort',
                    'is_final_semester': target >= total}

        passed = cls.completed_course_ids(student)
        semesters = list(curriculum.semesters.all())
        completed_semesters = 0
        for cs in sorted(semesters, key=lambda x: x.semester_number):
            required = list(cs.courses.filter(course_type='required'))
            if required and all(entry.course_id in passed for entry in required):
                completed_semesters = cs.semester_number
            elif not required:
                break
            else:
                break
        max_semester = max([s.semester_number for s in semesters], default=(student.active_program.duration_years or 4)*2)
        if current_semester and current_semester.semester_number:
            # Never advance beyond the institution's current term.
            cohort = getattr(student, 'admission_semester', None)
            if cohort and cohort.semester_number:
                cohort_target = current_semester.semester_number - cohort.semester_number + 1
                if cohort_target > 0:
                    # Do not advance a student merely because the calendar
                    # moved forward. Failed/unfinished required coursework
                    # keeps the academic position at the next incomplete
                    # curriculum semester, while the institutional term still
                    # caps how far ahead the student may be placed.
                    target = min(max_semester, cohort_target, max(1, completed_semesters + 1))
                else:
                    target = 1
            else:
                target = min(max_semester, max(1, completed_semesters + 1))
        else:
            target = min(max_semester, max(1, completed_semesters + 1))
        return {'year': (target + 1)//2, 'semester': target, 'total_semesters': max_semester,
                'completed_semesters': completed_semesters, 'source': 'curriculum',
                'is_final_semester': target >= max_semester}

    @staticmethod
    def active_curriculum(student):
        """The curriculum version a student is actually held to. Prefers the
        one PINNED on their Enrollment record at the time they enrolled, so a
        later change to the program's active curriculum never shifts an
        already-enrolled student's required semesters/courses underneath
        them. Falls back to the program's current active curriculum only
        when there is no enrollment record yet (e.g. legacy data)."""
        if not student or not student.active_program_id:
            return None
        enrollment = student.current_enrollment
        if enrollment and enrollment.curriculum_id:
            return enrollment.curriculum
        return (enrollment.program.curricula.filter(is_active=True)
                .prefetch_related('semesters__courses__course').order_by('-version').first())

    @classmethod
    def curriculum_entry(cls, student, course):
        """The student's active-curriculum entry for `course`, or None."""
        curriculum = cls.active_curriculum(student)
        if not curriculum:
            return None
        from academics.models import CurriculumCourse
        return (CurriculumCourse.objects.filter(curriculum_semester__curriculum=curriculum, course=course)
                .select_related('curriculum_semester').first())

    @classmethod
    def recommended_courses(cls, student, semester=None):
        """Required courses the student should take now, in priority order:
        carry-over/failed required courses from EARLIER curriculum semesters
        first, then this semester's required courses. Electives are never
        auto-recommended (the student must choose them). Passed and
        already-registered courses and unmet prerequisites are excluded."""
        semester = semester or cls.current_semester()
        position = cls.academic_position(student, semester)
        curriculum = cls.active_curriculum(student)
        if not position or not curriculum:
            return []
        passed = cls.completed_course_ids(student)
        active = set(CourseRegistration.objects.filter(student=student, status='registered', semester=semester)
                     .values_list('section__course_id', flat=True)) if semester else set()
        result = []
        for cs in sorted(curriculum.semesters.all(), key=lambda x: x.semester_number):
            if cs.semester_number > position['semester']:
                break
            for item in cs.courses.all():
                if item.course_type != 'required' or not item.recommended:
                    continue
                if item.course_id in passed or item.course_id in active:
                    continue
                if any(c.id not in passed for c in item.course.prerequisites.all()):
                    continue
                result.append(item)
        return result

    @classmethod
    def registration_eligibility(cls, student, section, semester=None):
        reasons = []
        semester = semester or cls.current_semester()
        if not student or student.status != 'active': reasons.append('Student account is not active.')
        if not student.active_program_id: reasons.append('No academic program is assigned.')
        if not semester: reasons.append('No active semester is configured.')
        now = timezone.now()
        if semester and not (semester.start_date <= timezone.localdate() <= semester.end_date): reasons.append('Registration is outside the semester dates.')
        if semester:
            state = semester.registration_state(now)
            if state == 'not_open':
                reasons.append(f'Course registration has not opened yet - it opens on {timezone.localtime(semester.registration_open):%d %b %Y, %H:%M}.')
            elif state == 'closed':
                reasons.append(f'Course registration deadline has passed - it closed on {timezone.localtime(semester.registration_close):%d %b %Y, %H:%M}.')
        if student.active_program_id and section.course.program_id != student.active_program_id: reasons.append('Course is not part of the student program curriculum.')
        if section.capacity <= 0 or section.seats_available_in(semester) <= 0: reasons.append('No seats are available in this section.')
        if semester and CourseRegistration.objects.filter(student=student, section__course=section.course, semester=semester, status='registered').exists(): reasons.append('Course is already registered for this semester.')
        if semester and student and student.pk:
            overlapping = (CourseRegistration.objects
                           .filter(student=student, section__course=section.course, status='registered',
                                   semester__start_date__lte=semester.end_date, semester__end_date__gte=semester.start_date)
                           .exclude(semester=semester).exists())
            if overlapping: reasons.append('Course is already registered under an overlapping semester record.')
        if student and student.active_program_id and semester:
            entry = cls.curriculum_entry(student, section.course)
            if cls.active_curriculum(student) and entry is None:
                reasons.append('Course is not part of your active curriculum.')
            elif entry is not None:
                position = cls.academic_position(student, semester)
                if position and entry.curriculum_semester.semester_number > position['semester']:
                    reasons.append(f'Course belongs to curriculum semester {entry.curriculum_semester.semester_number}; your current position is semester {position["semester"]}.')
        if student and student.pk and SiteSettings.load().block_registration_on_overdue_fees:
            from finance.models import Invoice
            if Invoice.objects.filter(student=student, paid=False, due_date__lt=timezone.localdate()).exists():
                reasons.append('Registration is on hold: you have an overdue unpaid fee challan.')
        passed = cls.passed_course_ids(student)
        if section.course_id in passed: reasons.append('Course has already been passed.')
        missing = [c.code for c in section.course.prerequisites.all() if c.id not in passed]
        if missing: reasons.append('Prerequisites not satisfied: ' + ', '.join(missing))
        conflict = cls._schedule_conflict(student, section, semester)
        if conflict: reasons.append(conflict)
        current_credits = sum((r.section.course.credits or 0) for r in CourseRegistration.objects.filter(student=student, semester=semester, status='registered').select_related('section__course')) if semester else 0
        limit = int(SiteSettings.load().max_registration_credits)
        if current_credits + (section.course.credits or 0) > limit: reasons.append(f'Credit-hour limit of {limit} would be exceeded.')
        return EligibilityResult(not reasons, tuple(reasons))

    @staticmethod
    def _schedule_conflict(student, section, semester):
        if not semester: return None
        from timetable.models import TimetableAssignment
        new_slots = list(TimetableAssignment.objects.filter(section=section, semester=semester).select_related('timeslot'))
        if not new_slots: return None
        other_ids = CourseRegistration.objects.filter(student=student, semester=semester, status='registered').exclude(section=section).values_list('section_id', flat=True)
        existing_slots = TimetableAssignment.objects.filter(section_id__in=other_ids, semester=semester).select_related('timeslot', 'section__course')
        for new in new_slots:
            for old in existing_slots:
                if old.timeslot.day == new.timeslot.day and old.timeslot.start_time < new.timeslot.end_time and new.timeslot.start_time < old.timeslot.end_time:
                    return f'Schedule conflict with {old.section.course.code} ({old.timeslot.get_day_display()} {old.timeslot.start_time}-{old.timeslot.end_time}).'
        return None

    @classmethod
    @transaction.atomic
    def register_course(cls, student, section_id, semester=None):
        semester = semester or cls.current_semester()
        section = CourseSection.objects.select_for_update().select_related('course', 'course__program').get(pk=section_id)
        result = cls.registration_eligibility(student, section, semester)
        if not result.eligible: raise ValueError(' '.join(result.reasons))
        return CourseRegistration.objects.create(student=student, section=section, semester=semester, status='registered')

    @classmethod
    def retake_improvement_options(cls, student, semester=None):
        from exams.models import canonical_grades
        entries = canonical_grades(
            GradeEntry.objects.filter(student=student).select_related('exam__course', 'exam__semester').order_by('-entered_at')
        )
        active = set(CourseRegistration.objects.filter(student=student, status='registered').values_list('section__course_id', flat=True))
        options = []
        for entry in entries:
            kind = 'retake' if entry.can_apply_retake else ('improvement' if entry.can_apply_improvement else None)
            if kind and entry.exam.course_id not in active:
                options.append({'grade_entry': entry, 'type': kind})
        return options

    @classmethod
    def auto_assign_current_courses(cls, student, semester=None, dry_run=False):
        semester = semester or cls.current_semester()
        created, skipped = [], []
        for item in cls.recommended_courses(student, semester):
            sections = sorted(CourseSection.objects.filter(course=item.course),
                              key=lambda sec: (-sec.seats_available_in(semester), sec.code))
            assigned = False
            for section in sections:
                check = cls.registration_eligibility(student, section, semester)
                if check.eligible:
                    if not dry_run:
                        created.append(cls.register_course(student, section.pk, semester))
                    else:
                        created.append(section)
                    assigned = True
                    break
            if not assigned:
                skipped.append({'course': item.course, 'reason': 'No eligible section available'})
        return {'created': created, 'skipped': skipped}


    @classmethod
    def auto_assign_all_students(cls, semester=None, dry_run=False):
        """Run automatic course assignment for EVERY active student (not one
        hand-picked student). One failing student never stops the rest: the
        error is recorded as an ExceptionRecord and the loop continues."""
        from core.models import ExceptionRecord
        semester = semester or cls.current_semester()
        totals = {'students': 0, 'registered': 0, 'skipped': 0, 'errors': 0}
        if not semester:
            return totals
        for student in Student.objects.filter(status='active').select_related('program', 'admission_semester'):
            totals['students'] += 1
            try:
                result = cls.auto_assign_current_courses(student, semester, dry_run=dry_run)
            except Exception as exc:  # recorded, never swallowed
                totals['errors'] += 1
                ExceptionRecord.objects.create(
                    code='auto_assign_failed', severity='warning', module='registration',
                    message=f'Automatic course assignment failed: {exc}',
                    object_type='Student', object_id=str(student.pk),
                    details={'semester_id': semester.pk},
                )
                continue
            totals['registered'] += len(result['created'])
            totals['skipped'] += len(result['skipped'])
        return totals


class AcademicProgressService:
    @staticmethod
    def standing_for(cgpa):
        """Academic standing from CGPA using the admin-configured thresholds."""
        if cgpa is None:
            return 'No Results Yet'
        cfg = SiteSettings.load()
        if cgpa < Decimal(str(cfg.probation_cgpa_threshold)):
            return 'Academic Probation'
        if cgpa >= Decimal(str(cfg.honor_cgpa_threshold)):
            return 'Honor Roll'
        return 'Good Standing'

    @staticmethod
    def calculate(student):
        """Course grade -> grade point -> credit x GP -> semester GPA -> CGPA
        -> standing. Per-semester GPA uses every canonical (one-per-semester)
        entry, so each semester's transcript history stays exactly as it
        happened. CGPA/standing/remaining-credits use best_attempt_per_course
        on top of that, so a retake/improvement REPLACES the earlier
        attempt's course credits in the cumulative total instead of adding
        to them - a failed course later passed on retake counts once, with
        its passing grade, never as two separate courses."""
        from exams.models import best_attempt_per_course, canonical_grades
        entries = canonical_grades(GradeEntry.objects.filter(student=student).select_related('exam__course', 'exam__semester'))
        cgpa_entries = best_attempt_per_course(entries)
        total_points = Decimal('0'); total_credits = Decimal('0'); failed = []
        for e in cgpa_entries:
            credits = Decimal(str(e.exam.course.credits or 0))
            points = Decimal(str(e.grade_point)) * credits
            total_points += points
            total_credits += credits
            if e.status == 'fail': failed.append(e)
        per_sem = {}
        for e in entries:
            credits = Decimal(str(e.exam.course.credits or 0))
            points = Decimal(str(e.grade_point)) * credits
            sem = e.exam.semester
            bucket = per_sem.setdefault(sem.pk if sem else None, {'semester': sem, 'points': Decimal('0'), 'credits': Decimal('0')})
            bucket['points'] += points
            bucket['credits'] += credits
        cgpa = (total_points / total_credits).quantize(Decimal('0.01')) if total_credits else None
        semester_gpas = []
        for bucket in per_sem.values():
            gpa = (bucket['points'] / bucket['credits']).quantize(Decimal('0.01')) if bucket['credits'] else None
            semester_gpas.append({'semester': bucket['semester'], 'credits': bucket['credits'], 'gpa': gpa})
        semester_gpas.sort(key=lambda x: (x['semester'].start_date if x['semester'] else timezone.localdate()))
        current = AcademicEligibilityService.current_semester()
        current_gpa = next((x['gpa'] for x in semester_gpas if x['semester'] and current and x['semester'].pk == current.pk), None)
        position = AcademicEligibilityService.academic_position(student)
        curriculum = AcademicEligibilityService.active_curriculum(student)
        remaining = None
        if curriculum and curriculum.total_credits:
            passed_credits = sum((Decimal(str(e.exam.course.credits or 0)) for e in cgpa_entries if e.status == 'pass'), Decimal('0'))
            remaining = max(Decimal('0'), Decimal(curriculum.total_credits) - passed_credits)
        return {'cgpa': cgpa, 'credits_attempted': total_credits, 'failed_entries': failed,
                'semester_gpas': semester_gpas, 'current_semester_gpa': current_gpa,
                'standing': AcademicProgressService.standing_for(cgpa),
                'remaining_credits': remaining, 'position': position}
