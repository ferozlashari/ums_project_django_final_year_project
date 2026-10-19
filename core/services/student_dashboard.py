"""Real-data modules for the student dashboard.

Every value comes from the database for THIS student. When there is nothing to
show the module says so (empty list) - nothing is estimated or invented.
"""
import datetime
from decimal import Decimal

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

DAY_CODES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


class StudentDashboardService:
    @staticmethod
    def _regs(student, semester):
        from academics.models import CourseRegistration
        if semester is None:
            return CourseRegistration.objects.none()
        return CourseRegistration.objects.filter(student=student, status='registered', semester=semester) \
            .select_related('section__course')

    @classmethod
    def todays_classes(cls, student, semester, now=None):
        from timetable.models import TimetableAssignment
        now = timezone.localtime(now or timezone.now())
        regs = list(cls._regs(student, semester))
        if not regs:
            return []
        slots = (TimetableAssignment.objects
                 .filter(section__in=[r.section for r in regs], status='approved',
                         timeslot__day=DAY_CODES[now.weekday()])
                 .filter(Q(semester=semester) | Q(semester__isnull=True))
                 .select_related('section__course', 'room', 'timeslot')
                 .order_by('timeslot__start_time'))
        t, rows = now.time(), []
        for a in slots:
            rows.append({
                'course': a.section.course, 'section': a.section, 'room': a.room.name,
                'start': a.timeslot.start_time, 'end': a.timeslot.end_time,
                'state': 'now' if a.timeslot.start_time <= t <= a.timeslot.end_time
                         else ('done' if a.timeslot.end_time < t else 'later'),
            })
        return rows

    @classmethod
    def upcoming(cls, student, semester, now=None, days=14):
        """Deadlines and events that need the student's attention, soonest first."""
        from assignments.models import Assignment
        from exams.models import ExamSession
        from exams.services_dynamic import SYNC_EXAM_NAME
        from onlineclass.models import OnlineClass
        from quizzes.models import Quiz, QuizAttempt
        now = now or timezone.now()
        regs = list(cls._regs(student, semester))
        if not regs:
            return []
        sections = [r.section for r in regs]
        course_ids = {r.section.course_id for r in regs}
        horizon = now + datetime.timedelta(days=days)
        items = []

        submitted = set(Assignment.objects.filter(section__in=sections, submissions__student=student)
                        .values_list('pk', flat=True))
        for a in Assignment.objects.filter(section__in=sections, due_date__gte=now - datetime.timedelta(days=7),
                                           due_date__lte=horizon).select_related('section__course'):
            if a.pk in submitted:
                continue
            overdue = a.due_date < now
            items.append({'kind': 'Assignment', 'icon': '📝', 'title': a.title, 'course': a.section.course.code,
                          'when': a.due_date, 'url': reverse('assignment-submit', args=[a.pk]),
                          'urgent': overdue or (a.due_date - now) <= datetime.timedelta(hours=48),
                          'note': 'overdue' if overdue else ''})

        for oc in OnlineClass.objects.filter(section__in=sections, status__in=['scheduled', 'live'],
                                             scheduled_at__gte=now - datetime.timedelta(hours=2),
                                             scheduled_at__lte=horizon).select_related('section__course'):
            items.append({'kind': 'Online class', 'icon': '🎥', 'title': oc.title, 'course': oc.section.course.code,
                          'when': oc.scheduled_at, 'url': reverse('class-list'),
                          'urgent': oc.status == 'live', 'note': 'live now' if oc.status == 'live' else ''})

        today = timezone.localdate(now)
        from exams.models import GradeEntry
        already_graded = set(GradeEntry.objects.filter(student=student).values_list('exam_id', flat=True))
        for ex in ExamSession.objects.filter(course_id__in=course_ids, date__gte=today,
                                             date__lte=today + datetime.timedelta(days=30)).exclude(name=SYNC_EXAM_NAME).exclude(pk__in=already_graded).select_related('course'):
            when = datetime.datetime.combine(ex.date, datetime.time(0, 0), tzinfo=timezone.get_current_timezone())
            items.append({'kind': 'Exam', 'icon': '🎫', 'title': ex.name, 'course': ex.course.code,
                          'when': when, 'url': reverse('my-exam-slip'),
                          'urgent': (ex.date - today).days <= 3, 'note': ''})
        items.sort(key=lambda i: i['when'])

        # Quizzes have no due date: list the ones still to take, after the dated items.
        taken = set(QuizAttempt.objects.filter(student=student, submitted_at__isnull=False).values_list('quiz_id', flat=True))
        for q in Quiz.objects.filter(section__in=sections, is_published=True).exclude(pk__in=taken).select_related('section__course'):
            items.append({'kind': 'Quiz', 'icon': '❓', 'title': q.title, 'course': q.section.course.code,
                          'when': None, 'url': reverse('quiz-take', args=[q.pk]), 'urgent': False,
                          'note': f'{q.time_limit_minutes} min'})
        return items

    @classmethod
    def degree_progress(cls, student):
        from core.services.academic import AcademicEligibilityService, AcademicProgressService
        p = AcademicProgressService.calculate(student)
        curriculum = AcademicEligibilityService.active_curriculum(student)
        total = Decimal(curriculum.total_credits) if curriculum and curriculum.total_credits else None
        remaining = p['remaining_credits']
        earned = (total - remaining) if (total is not None and remaining is not None) else None
        percent = int(min(100, max(0, earned / total * 100))) if (earned is not None and total) else None
        trend = [{'label': (g['semester'].name if g['semester'] else 'Unassigned'), 'gpa': g['gpa'],
                  'width': int(min(100, (g['gpa'] / Decimal('4')) * 100))}
                 for g in p['semester_gpas'] if g['gpa'] is not None]
        return {'cgpa': p['cgpa'], 'standing': p['standing'], 'total_credits': total, 'earned_credits': earned,
                'remaining_credits': remaining, 'percent': percent, 'trend': trend,
                'has_data': bool(trend) or p['cgpa'] is not None}

    @staticmethod
    def library(student):
        from library.models import BookLoan
        today = timezone.localdate()
        rows = []
        for loan in BookLoan.objects.filter(student=student, status='borrowed').select_related('book').order_by('due_date'):
            days = (loan.due_date - today).days
            rows.append({'book': loan.book, 'due': loan.due_date, 'days_left': days,
                         'overdue': days < 0, 'fine': loan.fine_amount})
        return rows

    @classmethod
    def build(cls, student, semester):
        return {
            'todays_classes': cls.todays_classes(student, semester),
            'upcoming': cls.upcoming(student, semester),
            'degree': cls.degree_progress(student),
            'library': cls.library(student),
        }
