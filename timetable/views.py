from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import TimetableAssignment, Room
from .forms import TimetableForm, RoomForm
from .utils import has_conflict
from core.permissions import staff_or_admin_required, admin_required


@login_required
def timetable_list(request):
    from core.views import _user_role
    entries = TimetableAssignment.objects.select_related('section', 'room', 'timeslot').all()
    role = _user_role(request.user)
    if role not in ('admin', 'staff', 'faculty'):
        # Students (and others) see only approved entries; students only for
        # sections they are registered in this semester.
        entries = entries.filter(status='approved')
        if role == 'student':
            from academics.models import CourseRegistration
            from core.services.academic import AcademicEligibilityService
            student = getattr(request.user, 'student_profile', None)
            entries = entries.filter(section_id__in=CourseRegistration.objects.filter(
                student=student, status='registered', semester=AcademicEligibilityService.current_semester(),
            ).values_list('section_id', flat=True)) if student else entries.none()
    return render(request, 'core/timetable.html', {'timetable': entries})


@staff_or_admin_required
def timetable_add(request):
    if request.method == 'POST':
        form = TimetableForm(request.POST)
        if form.is_valid():
            room = form.cleaned_data['room']
            timeslot = form.cleaned_data['timeslot']
            if has_conflict(TimetableAssignment.objects.all(), room, timeslot):
                form.add_error(None, f'{room} is already booked for {timeslot}. Choose a different room or time slot.')
            else:
                form.save()
                messages.success(request, 'Timetable entry added.')
                return redirect('timetable-list')
    else:
        form = TimetableForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Timetable Entry', 'cancel_url': '/timetable/'})


@login_required
def room_list(request):
    rooms = Room.objects.all()
    return render(request, 'timetable/room-list.html', {'rooms': rooms})


@staff_or_admin_required
def room_add(request):
    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classroom added.')
            return redirect('room-list')
    else:
        form = RoomForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Classroom', 'cancel_url': '/timetable/rooms/'})


@admin_required
def timetable_planner(request):
    """Conflict report + draft generation + approval (POST actions)."""
    from core.services.academic import AcademicEligibilityService
    from .services import TimetableService
    semester = AcademicEligibilityService.current_semester()
    if semester is None:
        messages.error(request, 'No active semester is configured.')
        return redirect('timetable-list')
    result = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'generate':
            result = TimetableService.generate(semester)
            messages.success(request, f"Draft created: {len(result['placed'])} placed, {len(result['unplaced'])} could not be placed.")
        elif action == 'approve':
            try:
                count = TimetableService.approve_drafts(semester)
                messages.success(request, f'{count} draft entries approved.')
            except ValueError as exc:
                messages.error(request, str(exc))
    drafts = TimetableAssignment.objects.filter(semester=semester, status='draft').select_related('section', 'room', 'timeslot')
    return render(request, 'timetable/planner.html', {
        'semester': semester, 'conflicts': TimetableService.conflicts(semester), 'drafts': drafts, 'result': result,
    })
