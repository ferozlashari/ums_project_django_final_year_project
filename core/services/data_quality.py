from core.models import DataQualityIssue
from registration.models import Student
from academics.models import CourseRegistration, CourseSection


class DataQualityService:
    """Non-destructive scanner for common academic integrity problems."""
    @classmethod
    def scan(cls):
        found = 0
        for student in Student.objects.filter(status='active'):
            if not student.active_program_id:
                cls._issue('missing_program', 'registration.Student', student.pk, f'Student {student.admission_no} has no program.', {'admission_no': student.admission_no}); found += 1
        for student in Student.objects.filter(status='active', program__isnull=False).select_related('program'):
            if student.active_program_id != student.program_id:
                cls._issue('enrollment_mismatch', 'registration.Student', student.pk,
                           f'Student {student.admission_no}: program column and active enrollment disagree. The enrollment is the source of truth.',
                           {'admission_no': student.admission_no}); found += 1
        for reg in CourseRegistration.objects.filter(status='registered').select_related('student','section','semester'):
            if reg.student.active_program_id != reg.section.course.program_id:
                cls._issue('program_mismatch', 'academics.CourseRegistration', reg.pk, 'Registered course does not belong to the student program.', {'student': reg.student_id, 'course': reg.section.course_id}); found += 1
            if not reg.semester:
                cls._issue('missing_semester', 'academics.CourseRegistration', reg.pk, 'Active registration has no semester.', {}); found += 1
        return found

    @staticmethod
    def _issue(issue_type, model_label, object_id, message, details):
        DataQualityIssue.objects.update_or_create(
            issue_type=issue_type, model_label=model_label, object_id=str(object_id), status='open',
            defaults={'message': message, 'details': details},
        )
