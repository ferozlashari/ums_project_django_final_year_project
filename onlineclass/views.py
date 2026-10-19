from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import OnlineClass
from .forms import OnlineClassForm
from django.core.exceptions import PermissionDenied
from core.permissions import can_manage_section, staff_or_admin_required, user_role
from core.models import notify_many


@login_required
def class_list(request):
    role = user_role(request.user)
    classes = OnlineClass.objects.select_related('section', 'section__course', 'host', 'host__user').all()

    empty_hint = ''
    if role == 'student':
        try:
            student = request.user.student_profile
            # Registered-section-scoped, not whole-program (see the
            # identical fix in assignments/views.py assignment_list) - a
            # student should only see online classes for sections they're
            # actually registered in, not every section of every course
            # in their program.
            from academics.models import CourseRegistration
            from core.services.academic import AcademicEligibilityService
            current = AcademicEligibilityService.current_semester()
            registered_section_ids = CourseRegistration.objects.filter(
                student=student, status='registered', semester=current,
            ).values_list('section_id', flat=True)
            classes = classes.filter(section_id__in=registered_section_ids)
            if current is None:
                empty_hint = 'No active semester is configured, so no classes can be shown yet.'
            elif not registered_section_ids:
                empty_hint = 'You are not registered in any course section this semester. Register from Course Selection - live classes only appear for sections you are registered in.'
        except (AttributeError, ObjectDoesNotExist):
            classes = OnlineClass.objects.none()
            empty_hint = 'No student record is linked to this account.'
    elif role in ('faculty', 'staff') and role != 'admin':
        try:
            staff = request.user.staff_profile
            classes = classes.filter(host=staff)
        except Exception:
            pass

    # A class's real end time (scheduled_at + its own duration_mins) is
    # computed here in Python rather than as a DB expression: multiplying
    # an integer field by a timedelta to add it to a DateTimeField is not
    # portable across backends (it raises "Invalid arguments for operator
    # *" on SQLite, even though it works on PostgreSQL). Bounded to the
    # 500 most recent by scheduled_at so this stays cheap even after
    # years of history, since future classes are always few and recent
    # past ones are all "Past Classes" needs. A class that finished hours
    # ago but was never manually "Ended" moves to Past Classes on its
    # own, instead of sitting in Upcoming forever.
    classes = list(classes.order_by('-scheduled_at')[:500])
    upcoming = sorted(
        (c for c in classes if c.display_status != 'ended'),
        key=lambda c: c.scheduled_at,
    )
    past = [c for c in classes if c.display_status == 'ended'][:20]
    return render(request, 'onlineclass/list.html', {'upcoming': upcoming, 'past': past, 'role': role, 'empty_hint': empty_hint})


@staff_or_admin_required
def class_schedule(request):
    if request.method == 'POST':
        form = OnlineClassForm(request.POST)
        if form.is_valid():
            oc = form.save(commit=False)
            try:
                oc.host = request.user.staff_profile
            except Exception:
                messages.error(request, 'Only teaching staff with a Staff profile can host classes.')
                return redirect('class-list')
            if not oc.semester:
                from core.services.academic import AcademicEligibilityService
                oc.semester = AcademicEligibilityService.current_semester()
            oc.save()
            from registration.models import Student
            from academics.models import CourseRegistration
            registered_student_ids = CourseRegistration.objects.filter(
                section=oc.section, status='registered',
            ).values_list('student_id', flat=True)
            students = Student.objects.filter(id__in=registered_student_ids).select_related('user')
            notify_many(
                [s.user for s in students],
                f'Online class scheduled: {oc.title}',
                f'{oc.section.course.code} - {oc.scheduled_at.strftime("%b %d, %H:%M")}. Join from Online Classes.',
                level='info', url='/classes/',
            )
            messages.success(request, f'Class "{oc.title}" scheduled. Share the room code with your students.')
            return redirect('class-list')
    else:
        form = OnlineClassForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Schedule Online Class', 'cancel_url': '/classes/'})


@login_required
def class_join(request, pk):
    oc = get_object_or_404(OnlineClass, pk=pk)
    role = user_role(request.user)

    if role == 'student':
        try:
            student = request.user.student_profile
            from academics.models import CourseRegistration
            reg = CourseRegistration.objects.filter(student=student, section=oc.section, status='registered', semester=oc.semester).first()
            if not reg:
                raise PermissionDenied("You are not registered in this course section for this semester.")
        except AttributeError:
            raise PermissionDenied("No student record linked to this account.")
    elif role in ('faculty', 'staff'):
        pass  # any teaching staff can join/host
    # admin always allowed

    # Joining is read-only. Status transitions belong to an explicit POST action.

    is_verified = False
    if role == 'student':
        from biometrics.models import OnlineClassAttendance
        is_verified = OnlineClassAttendance.objects.filter(online_class=oc, student=request.user.student_profile, registration__semester=oc.semester).exists()

    return render(request, 'onlineclass/join.html', {'oc': oc, 'role': role, 'is_verified': is_verified})


@staff_or_admin_required
@require_POST
def class_end(request, pk):
    oc = get_object_or_404(OnlineClass, pk=pk)
    if not can_manage_section(request.user, oc.section, write=True):
        raise PermissionDenied('Only the class\'s own teacher can end it.')
    oc.status = 'ended'
    oc.save(update_fields=['status'])
    messages.success(request, f'Class "{oc.title}" marked as ended.')
    return redirect('class-list')
