from decimal import Decimal
from django.db import transaction
from .models import AssessmentMark, AssessmentScheme, ResultPublication


class DynamicAssessmentService:
    """Raw marks in; weighted total, percentage and grade out."""
    @staticmethod
    def calculate(registration, scheme=None):
        scheme = scheme or AssessmentScheme.objects.filter(course=registration.section.course, is_active=True).prefetch_related('components').order_by('-version').first()
        if not scheme:
            return {'total': Decimal('0'), 'percentage': Decimal('0'), 'complete': False, 'scheme': None}
        marks = AssessmentMark.objects.filter(registration=registration, component__scheme=scheme).select_related('component')
        by_component = {m.component_id: m for m in marks}
        total = Decimal('0'); complete = True
        for component in scheme.components.all():
            mark = by_component.get(component.id)
            if mark is None or mark.raw_marks is None:
                if component.is_required: complete = False
                continue
            total += mark.weighted_marks
        return {'total': total.quantize(Decimal('0.01')), 'percentage': total.quantize(Decimal('0.01')), 'complete': complete, 'scheme': scheme}

    @classmethod
    @transaction.atomic
    def enter_mark(cls, registration, component, raw_marks, user=None):
        if component.scheme.course_id != registration.section.course_id:
            raise ValueError('Assessment component does not belong to this course.')
        mark, _ = AssessmentMark.objects.update_or_create(
            registration=registration, component=component,
            defaults={'raw_marks': raw_marks, 'entered_by': user},
        )
        mark.full_clean(); mark.save()
        return mark


SYNC_EXAM_NAME = 'Final Result (Assessment Scheme)'


class ResultPublicationService:
    FLOW = ['teacher_submitted', 'department_verified', 'exam_verified', 'published']

    # -- bridge to the GradeEntry ledger --------------------------------------
    # Results page, GPA/CGPA, academic standing, risk scoring and retake
    # eligibility all read GradeEntry. A result published through the
    # assessment-scheme workflow must therefore be written there, or the
    # student would never see it and it would never count. It lives in its
    # own clearly named ExamSession so it never overwrites a legacy entry
    # (canonical_grades keeps the most recent one per student/course/semester).
    @classmethod
    def sync_grade_entry(cls, registration, user=None):
        from django.utils import timezone
        from .models import ExamSession, GradeEntry
        calc = DynamicAssessmentService.calculate(registration)
        session, _ = ExamSession.objects.get_or_create(
            course=registration.section.course, semester=registration.semester, name=SYNC_EXAM_NAME,
            defaults={'date': timezone.localdate(), 'max_marks': Decimal('100')})
        entry, _ = GradeEntry.objects.update_or_create(
            student=registration.student, exam=session,
            defaults={'registration': registration, 'marks': calc['percentage'], 'entered_by': user,
                      'attempt_type': 'regular'})
        return entry

    @classmethod
    def unsync_grade_entry(cls, registration):
        """Remove the published ledger entry (on reopen). Returns the removed entry's
        (marks, grade) so the caller can preserve the old value in the audit log."""
        from .models import GradeEntry
        entry = GradeEntry.objects.filter(registration=registration, exam__name=SYNC_EXAM_NAME).first()
        old = (entry.marks, entry.grade) if entry else None
        if entry:
            entry.delete()
        return old

    @classmethod
    @transaction.atomic
    def advance(cls, registration, target, user=None):
        if target not in cls.FLOW:
            raise ValueError('Invalid result publication state.')
        current = getattr(registration, 'result_publication', None)
        if current is None:
            current = ResultPublication.objects.create(registration=registration, updated_by=user)
        if current.status == 'reopened':
            # An officer sent it back: the teacher may only resubmit from the start.
            if target != 'teacher_submitted':
                raise ValueError('A reopened result must be resubmitted by the teacher first.')
            current_index, target_index = -1, 0
        else:
            current_index = cls.FLOW.index(current.status)
            target_index = cls.FLOW.index(target)
        if target_index > current_index + 1:
            raise ValueError('Result publication states must advance one stage at a time.')
        current.status = target
        current.updated_by = user
        from django.utils import timezone
        if target in ('department_verified','exam_verified'):
            current.verified_at = timezone.now()
        if target == 'published':
            current.published_at = timezone.now()
        current.save()
        if target == 'published':
            cls.sync_grade_entry(registration, user=user)
        return current
