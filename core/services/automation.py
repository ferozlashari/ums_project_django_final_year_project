from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from core.models import Notification, notify, SiteSettings
from finance.models import Invoice
from registration.models import Student
from attendance.models import AttendanceRecord

class AutomationService:
    """Idempotent, safe housekeeping. Run from cron/Task Scheduler/management command, or the Automation Center button in the UI (core.views.run_automation_view)."""
    TASKS = ('housekeeping', 'course_assignment', 'fee_challans', 'late_fees', 'academic_standing')

    @classmethod
    def run(cls, dry_run=False, only=None, trigger='service'):
        """Run every automation task as its own AutomationTask row.

        Idempotent (re-running never duplicates registrations or
        notifications), auditable (AutomationRun/Task history), traceable
        (per-task result JSON) and retryable (a failed task is recorded with
        its error + an ExceptionRecord, the other tasks still run, and the
        run finishes as 'partial' instead of hanging in 'running')."""
        from core.models import AutomationRun, AutomationTask, ExceptionRecord
        run = AutomationRun.objects.create(trigger=trigger, status='running', dry_run=dry_run, started_at=timezone.now())
        stats, failures = {}, 0
        for name in (only or cls.TASKS):
            task = AutomationTask.objects.create(run=run, name=name, status='running', started_at=timezone.now(), attempts=1)
            try:
                with transaction.atomic():
                    result = getattr(cls, f'_task_{name}')(dry_run)
                task.status, task.result = 'completed', result
                stats.update(result)
            except Exception as exc:
                failures += 1
                task.status, task.error = 'failed', f'{type(exc).__name__}: {exc}'
                ExceptionRecord.objects.create(
                    code='automation_task_failed', severity='warning', module='automation',
                    message=f'Automation task "{name}" failed: {exc}',
                    object_type='AutomationTask', object_id=str(task.pk),
                    details={'run_id': run.pk, 'task': name},
                )
            task.finished_at = timezone.now()
            task.save(update_fields=['status', 'finished_at', 'result', 'error'])
        run.status = 'completed' if not failures else ('failed' if failures == len(only or cls.TASKS) else 'partial')
        run.finished_at = timezone.now()
        run.summary = stats
        if failures:
            run.error = f'{failures} task(s) failed - see the task list and Exception Center.'
        run.save(update_fields=['status', 'finished_at', 'summary', 'error'])
        return stats

    @classmethod
    def _task_housekeeping(cls, dry_run):
        today=timezone.localdate(); due_soon=today+timedelta(days=3); stats={'fee_due':0,'overdue':0,'low_attendance':0,'registration_deadline':0,'data_quality':0}
        min_attendance = float(SiteSettings.load().minimum_attendance_percent)
        for inv in Invoice.objects.select_related('student__user').filter(paid=False):
            if inv.due_date == due_soon:
                stats['fee_due']+=1
                if not dry_run: cls._notify_once(inv.student.user, 'Fee due soon', f'{inv.challan_no} is due on {inv.due_date}.', inv.pk)
            if inv.due_date and inv.due_date < today:
                stats['overdue']+=1
        from core.services.academic import AcademicEligibilityService
        current_semester = AcademicEligibilityService.current_semester()
        for student in Student.objects.select_related('user'):
            records=AttendanceRecord.objects.filter(student=student, semester=current_semester) if current_semester else AttendanceRecord.objects.none(); total=records.count()
            if total:
                pct=records.filter(present=True).count()*100/total
                if pct < min_attendance:
                    stats['low_attendance']+=1
                    if not dry_run: cls._notify_once(student.user,'Low attendance warning',f'Your attendance is {pct:.1f}%. Minimum required attendance is {min_attendance}% - review this before exams.',student.pk)
        stats['registration_deadline'] = cls._registration_deadline_reminders(dry_run)
        if not dry_run:
            from core.services.data_quality import DataQualityService
            stats['data_quality'] = DataQualityService.scan()
        return stats

    @classmethod
    def _task_course_assignment(cls, dry_run):
        """Curriculum-driven automatic registration for EVERY active student."""
        from core.services.academic import AcademicEligibilityService
        totals = AcademicEligibilityService.auto_assign_all_students(dry_run=dry_run)
        return {'assign_students': totals['students'], 'assign_registered': totals['registered'],
                'assign_skipped': totals['skipped'], 'assign_errors': totals['errors']}

    @classmethod
    def _task_fee_challans(cls, dry_run):
        """Automatically raise every challan a student owes, from real data:
        the current semester's program-wise tuition (once per semester, for
        students registered in it), hostel/transport fees for students who
        actually hold a room/route, and the one-time degree fee for students
        in their final semester. Idempotent - re-running never duplicates."""
        from academics.models import CourseRegistration
        from finance.services import FeeChallanService
        from core.services.academic import AcademicEligibilityService
        semester = AcademicEligibilityService.current_semester()
        stats = {'challan_semester': 0, 'challan_hostel': 0, 'challan_transport': 0, 'challan_degree': 0}
        if semester is None:
            return stats
        registered_ids = set(CourseRegistration.objects.filter(semester=semester, status='registered').values_list('student_id', flat=True))
        for student in Student.objects.filter(status='active').select_related('user', 'program'):
            wanted = []
            if student.pk in registered_ids and student.active_program_id:
                wanted.append(('challan_semester', FeeChallanService.generate_semester_fee, not Invoice.objects.filter(student=student, category='semester', semester=semester).exists()))
            wanted.append(('challan_hostel', FeeChallanService.generate_hostel_fee, True))
            wanted.append(('challan_transport', FeeChallanService.generate_transport_fee, not Invoice.objects.filter(student=student, category='transport', semester=semester).exists() and not Invoice.objects.filter(student=student, category='transport', paid=False).exists()))
            wanted.append(('challan_degree', FeeChallanService.generate_degree_fee, True))
            for key, fn, needed in wanted:
                if not needed:
                    continue
                before = Invoice.objects.filter(student=student).count()
                if dry_run:
                    continue
                result = fn(student)
                if result.ok and Invoice.objects.filter(student=student).count() > before:
                    stats[key] += 1
        return stats

    @classmethod
    def _task_late_fees(cls, dry_run):
        """Issue the one late-penalty challan for each unpaid challan that is
        past its due date plus the configured grace days."""
        from finance.services import FeeChallanService
        from governance.policy import resolve
        grace = int(resolve('finance.late_fee_grace_days', default=0) or 0)
        cutoff = timezone.localdate() - timedelta(days=grace)
        issued = 0
        for inv in Invoice.objects.filter(paid=False, due_date__lt=cutoff).exclude(category='penalty').select_related('student__user'):
            if dry_run:
                continue
            if FeeChallanService.issue_late_fee(inv, grace_days=grace).ok:
                issued += 1
        return {'late_fees_issued': issued}

    @classmethod
    def _task_academic_standing(cls, dry_run):
        """Flag students whose CGPA has fallen below the probation threshold
        (notification only - standing itself is always computed live)."""
        from core.services.academic import AcademicProgressService
        probation = 0
        for student in Student.objects.filter(status='active').select_related('user'):
            progress = AcademicProgressService.calculate(student)
            if progress['standing'] == 'Academic Probation':
                probation += 1
                if not dry_run:
                    cls._notify_once(student.user, 'Academic probation notice',
                                     f'Your CGPA is {progress["cgpa"]}, below the required minimum. Please meet your academic advisor.', student.pk)
        return {'probation': probation}

    @classmethod
    def _registration_deadline_reminders(cls, dry_run):
        """Warn students whose current semester's registration window is
        closing within 3 days and who have not registered anything yet -
        the 'registration deadline approaching -> reminder' event."""
        from academics.models import Semester
        now = timezone.now()
        soon = now + timedelta(days=3)
        count = 0
        closing_semesters = Semester.objects.filter(registration_close__gte=now, registration_close__lte=soon)
        for semester in closing_semesters:
            students_without_registration = Student.objects.filter(status='active').exclude(
                course_registrations__semester=semester, course_registrations__status='registered',
            ).select_related('user')
            for student in students_without_registration:
                count += 1
                if not dry_run:
                    cls._notify_once(
                        student.user, 'Course registration deadline approaching',
                        f'Registration for {semester.name} closes on {semester.registration_close:%Y-%m-%d %H:%M}. You have not registered for any courses yet.',
                        f'regdeadline-{semester.pk}',
                    )
        return count

    @staticmethod
    def _notify_once(user,title,message,key):
        exists=Notification.objects.filter(user=user,title=title,message=message,created_at__gte=timezone.now()-timedelta(hours=24)).exists()
        if not exists: notify(user,title,message,level='warning')
