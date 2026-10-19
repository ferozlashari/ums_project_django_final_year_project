from dataclasses import dataclass
from django.utils import timezone
from academics.models import CourseRegistration
from attendance.models import AttendanceRecord
from finance.models import Invoice
from exams.models import ExamSession
from core.models import SiteSettings

@dataclass(frozen=True)
class ExamEligibility:
    eligible: bool
    reasons: tuple[str, ...]
    attendance_percent: float

class ExamEligibilityService:
    DEFAULT_MIN_ATTENDANCE = 80.0
    @classmethod
    def for_course(cls, student, course, semester=None, min_attendance=None):
        reasons=[]
        reg = CourseRegistration.objects.filter(student=student, section__course=course, status='registered')
        if semester: reg = reg.filter(semester=semester)
        registration = reg.select_related('section').first()
        if not registration: reasons.append('Course is not currently registered.')
        records = AttendanceRecord.objects.filter(student=student, section__course=course)
        total=records.count(); present=records.filter(present=True).count(); pct=round((present/total)*100,1) if total else 0.0
        required = float(min_attendance if min_attendance is not None else SiteSettings.load().minimum_attendance_percent)
        if pct < required: reasons.append(f'Attendance is {pct}% but {required:.0f}% is required.')
        unpaid = Invoice.objects.filter(student=student, paid=False).exists()
        if unpaid: reasons.append('Outstanding fee challan must be cleared.')
        return ExamEligibility(not reasons, tuple(reasons), pct)

    @classmethod
    def eligible_exams(cls, student, semester=None):
        # Student -> active enrollment -> registered section -> exam session.
        # An exam is only offered for a course the student is actually
        # registered in (and that belongs to their enrolled program).
        from academics.models import CourseRegistration
        reg = CourseRegistration.objects.filter(student=student, status='registered', section__course__program=student.active_program_id)
        if semester: reg = reg.filter(semester=semester)
        qs = ExamSession.objects.filter(course_id__in=reg.values_list('section__course_id', flat=True))
        if semester: qs = qs.filter(semester=semester)
        out=[]
        for exam in qs.select_related('course','semester').order_by('date'):
            result=cls.for_course(student, exam.course, semester=exam.semester)
            if result.eligible: out.append((exam,result))
        return out
