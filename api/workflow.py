from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from core.services.academic import AcademicEligibilityService, AcademicProgressService
from core.services.exams import ExamEligibilityService
from core.services.finance import FeeEligibilityService, PaymentService
from registration.models import Student
from academics.models import CourseSection
from finance.models import Invoice
from core.permissions import user_role


def own_student(request):
    if user_role(request.user) != 'student':
        return None
    return Student.objects.filter(user=request.user).select_related('program').first()

class MyAcademicSummaryAPI(APIView):
    def get(self, request):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        progress=AcademicProgressService.calculate(student)
        options=AcademicEligibilityService.retake_improvement_options(student)
        return Response({'student_id':student.id,'admission_no':student.admission_no,'program':student.active_program.name if student.active_program else None,'cgpa':progress['cgpa'],'current_semester_gpa':progress['current_semester_gpa'],'standing':progress['standing'],'remaining_credits':progress['remaining_credits'],'semester_gpas':[{'semester':(x['semester'].display_name if x['semester'] else None),'gpa':x['gpa'],'credits':x['credits']} for x in progress['semester_gpas']],'credits_attempted':progress['credits_attempted'],'failed_courses':len(progress['failed_entries']),'retake_improvement_options':[{'grade_entry_id':o['grade_entry'].id,'type':o['type'],'course':o['grade_entry'].exam.course.code} for o in options]})

class EligibleSectionsAPI(APIView):
    def get(self, request):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        sections=CourseSection.objects.filter(course__program=student.active_program).select_related('course').prefetch_related('course__prerequisites')
        data=[]
        for section in sections:
            result=AcademicEligibilityService.registration_eligibility(student,section)
            data.append({'id':section.id,'course_code':section.course.code,'course_name':section.course.name,'credits':section.course.credits,'section':section.code,'seats_available':section.seats_available,'eligible':result.eligible,'reasons':list(result.reasons)})
        return Response(data)

class MyExamEligibilityAPI(APIView):
    def get(self, request):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        rows=[]
        for exam,result in ExamEligibilityService.eligible_exams(student):
            rows.append({'exam_id':exam.id,'course_code':exam.course.code,'course_name':exam.course.name,'date':exam.date,'eligible':result.eligible,'attendance_percent':result.attendance_percent,'reasons':list(result.reasons)})
        return Response(rows)

class MyFeesAPI(APIView):
    def get(self, request):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        invoices=FeeEligibilityService.unpaid(student)
        return Response({'outstanding':sum((i.amount for i in invoices), 0),'items':[{'id':i.id,'challan_no':i.challan_no,'category':i.category,'amount':i.amount,'due_date':i.due_date,'overdue':i.is_overdue} for i in invoices]})

class RegisterCourseAPI(APIView):
    def post(self, request):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        try: reg=AcademicEligibilityService.register_course(student, int(request.data.get('section_id')))
        except (ValueError, TypeError): return Response({'detail':'A valid section_id is required.'}, status=400)
        except CourseSection.DoesNotExist: return Response({'detail':'Section not found.'}, status=404)
        except Exception: return Response({'detail':'Course registration could not be completed.'}, status=409)
        return Response({'id':reg.id,'status':reg.status,'semester_id':reg.semester_id}, status=status.HTTP_201_CREATED)

class SubmitPaymentAPI(APIView):
    def post(self, request, invoice_id):
        student=own_student(request)
        if not student: return Response({'detail':'Student access required.'}, status=403)
        invoice=get_object_or_404(Invoice, pk=invoice_id, student=student)
        try:
            payment=PaymentService.submit(invoice.id, invoice.amount, request.data.get('method',''), request.data.get('transaction_id',''))
        except ValueError as exc: return Response({'detail':str(exc)}, status=400)
        return Response({'id':payment.id,'status':payment.status,'challan_no':invoice.challan_no}, status=201)


class MyAttendanceAPI(APIView):
    """Per-course attendance summary for the signed-in student - same
    percentage calculation the exam-slip eligibility check uses, exposed
    read-only over the API for a mobile client."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        from attendance.models import AttendanceRecord
        from django.db.models import Count, Q
        rows = (
            AttendanceRecord.objects.filter(student=student, section__isnull=False)
            .values('section_id', 'section__course__code', 'section__course__name')
            .annotate(total=Count('id'), present=Count('id', filter=Q(present=True)))
        )
        data = [
            {
                'section_id': r['section_id'], 'course_code': r['section__course__code'],
                'course_name': r['section__course__name'], 'total_classes': r['total'],
                'present': r['present'],
                'percentage': round((r['present'] / r['total']) * 100, 1) if r['total'] else 0,
            }
            for r in rows
        ]
        return Response({'attendance': data})


class MyLibraryAPI(APIView):
    """Current + past book loans and any outstanding fines for the
    signed-in student."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        from library.models import BookLoan
        loans = BookLoan.objects.filter(student=student).select_related('book').order_by('-borrowed_at')[:50]
        data = [
            {
                'id': l.id, 'book_title': l.book.title, 'borrowed_at': l.borrowed_at,
                'due_date': l.due_date, 'returned_at': l.returned_at, 'status': l.status,
                'fine_amount': str(l.fine_amount),
            }
            for l in loans
        ]
        outstanding_fines = sum((l.fine_amount for l in loans if l.fine_amount and l.status == 'borrowed'), start=0)
        return Response({'loans': data, 'outstanding_fines': str(outstanding_fines)})


class MyHostelAPI(APIView):
    """The signed-in student's hostel application status and room
    allocation, if any."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        from hostel.models import HostelApplication
        app = HostelApplication.objects.filter(student=student).select_related('hostel', 'assigned_room').order_by('-applied_at').first()
        if not app:
            return Response({'has_application': False})
        return Response({
            'has_application': True, 'status': app.status,
            'hostel': app.hostel.name if app.hostel else None,
            'room_type_preference': app.room_type_preference,
            'assigned_room': str(app.assigned_room) if app.assigned_room else None,
            'applied_at': app.applied_at,
        })


class MyTransportAPI(APIView):
    """The signed-in student's transport route assignment, if any."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        assignment = getattr(student, 'transport_assignment', None)
        if not assignment or not assignment.is_active:
            return Response({'has_assignment': False})
        return Response({
            'has_assignment': True, 'route': assignment.route.name,
            'stop': assignment.stop.name if assignment.stop else None,
            'fare_per_semester': str(assignment.route.fare_per_semester),
        })


class MyTimetableAPI(APIView):
    """The signed-in student's weekly class schedule, derived from their
    current registered sections - the same data the web timetable page
    shows, just as JSON."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        from timetable.models import TimetableAssignment
        section_ids = student.course_registrations.filter(status='registered').values_list('section_id', flat=True)
        entries = TimetableAssignment.objects.filter(section_id__in=section_ids).select_related('section__course', 'room', 'timeslot')
        data = [
            {
                'course_code': t.section.course.code, 'course_name': t.section.course.name,
                'section': t.section.code, 'room': t.room.name,
                'day': t.timeslot.day, 'start_time': str(t.timeslot.start_time), 'end_time': str(t.timeslot.end_time),
            }
            for t in entries
        ]
        return Response({'timetable': data})


class MyQuizzesAPI(APIView):
    """Published quizzes for the signed-in student's registered sections,
    with their own attempt status/score if already taken."""
    def get(self, request):
        student = own_student(request)
        if not student: return Response({'detail': 'Student access required.'}, status=403)
        from quizzes.models import Quiz, QuizAttempt
        section_ids = student.course_registrations.filter(status='registered').values_list('section_id', flat=True)
        quizzes = Quiz.objects.filter(section_id__in=section_ids, is_published=True).select_related('section__course')
        attempts = {a.quiz_id: a for a in QuizAttempt.objects.filter(student=student, quiz__in=quizzes)}
        data = [
            {
                'id': q.id, 'title': q.title, 'course_code': q.section.course.code,
                'time_limit_minutes': q.time_limit_minutes,
                'attempted': q.id in attempts,
                'score': attempts[q.id].score if q.id in attempts else None,
            }
            for q in quizzes
        ]
        return Response({'quizzes': data})


class MyNotificationsAPI(APIView):
    """The signed-in user's own notifications - any role, not just
    students (a teacher or admin has notifications too)."""
    def get(self, request):
        from core.models import Notification
        all_notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
        unread_count = all_notifications.filter(is_read=False).count()
        notifications = all_notifications[:50]
        data = [
            {'id': n.id, 'title': n.title, 'message': n.message, 'level': n.level, 'url': n.url, 'read': n.is_read, 'created_at': n.created_at}
            for n in notifications
        ]
        return Response({'notifications': data, 'unread_count': unread_count})


class MyComplaintsAPI(APIView):
    """The signed-in user's own submitted complaints and their status -
    any role."""
    def get(self, request):
        from complaints.models import Complaint
        complaints = Complaint.objects.filter(user=request.user).order_by('-created_at')[:50]
        data = [
            {'id': c.id, 'category': c.category, 'subject': c.subject, 'status': c.status, 'created_at': c.created_at}
            for c in complaints
        ]
        return Response({'complaints': data})
