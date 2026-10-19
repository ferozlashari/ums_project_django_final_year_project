from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Room, HostelApplication, Hostel
from .forms import HostelApplicationForm, RoomForm, AssignRoomForm, HostelForm
from core.permissions import staff_or_admin_required, admin_required, office_staff_required, user_role
from core.models import notify

HOSTEL_FEE_AMOUNT = Decimal('25000')  # per-semester hostel fee, generated on approval


@login_required
def apply_hostel(request):
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can apply for hostel accommodation.')
        return redirect('hostel-my-application')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('dashboard')

    existing = HostelApplication.objects.filter(student=student).exclude(status='rejected').first()
    if existing:
        messages.info(request, 'You already have an active hostel application.')
        return redirect('hostel-my-application')

    if not student.gender:
        messages.error(request, 'Set your gender in your profile first - hostels are gender-separated, so we need this to show you the right options.')
        return redirect('hostel-my-application')

    # Show real room availability, scoped to hostels matching the student's
    # gender only - a male applicant never even sees a girls' hostel and
    # vice versa.
    gender_hostels = Hostel.objects.filter(is_active=True, gender=student.gender)
    rooms = Room.objects.filter(hostel__in=gender_hostels).select_related('hostel')
    availability_by_type = {}
    for choice_value, choice_label in Room.ROOM_TYPE_CHOICES:
        type_rooms = [r for r in rooms if r.room_type == choice_value]
        open_rooms = [r for r in type_rooms if not r.is_full]
        availability_by_type[choice_value] = {
            'label': choice_label, 'rooms': type_rooms,
            'open_count': len(open_rooms), 'total_count': len(type_rooms),
        }

    if request.method == 'POST':
        form = HostelApplicationForm(request.POST, request.FILES, student_gender=student.gender)
        if form.is_valid():
            app = form.save(commit=False)
            app.student = student
            app.save()
            from finance.models import Invoice
            invoice = Invoice.objects.create(
                student=student, category='hostel', amount=HOSTEL_FEE_AMOUNT,
                reference=f'Hostel application - {app.hostel.name} ({app.get_room_type_preference_display()})',
            )
            notify(
                student.user, f'Hostel fee challan: {invoice.challan_no}',
                f'Pay {invoice.amount} to secure your hostel spot while it is reviewed.',
                level='warning', url=reverse('challan-detail', kwargs={'pk': invoice.pk}),
            )
            messages.success(request, f'Hostel application submitted. Fee challan {invoice.challan_no} generated - pay it to secure your spot while your room assignment is reviewed.')
            return redirect('challan-detail', pk=invoice.pk)
    else:
        form = HostelApplicationForm(student_gender=student.gender)
    return render(request, 'hostel/apply.html', {
        'form': form, 'title': 'Apply for Hostel', 'cancel_url': '/hostel/',
        'availability_by_type': availability_by_type, 'gender_hostels': gender_hostels,
    })


@login_required
def my_application(request):
    if user_role(request.user) != 'student':
        return redirect('hostel-manage')
    try:
        student = request.user.student_profile
        applications = HostelApplication.objects.filter(student=student).select_related('assigned_room')
    except Exception:
        applications = HostelApplication.objects.none()
    return render(request, 'hostel/my_application.html', {'applications': applications})


@office_staff_required
def manage_applications(request):
    applications = HostelApplication.objects.select_related('student', 'assigned_room').order_by('-applied_at')
    return render(request, 'hostel/manage.html', {'applications': applications})


@office_staff_required
def review_application(request, pk):
    app = get_object_or_404(HostelApplication, pk=pk)
    if request.method == 'POST':
        form = AssignRoomForm(request.POST, instance=app)
        if form.is_valid():
            app = form.save()
            notify(
                app.student.user, f'Hostel application {app.get_status_display().lower()}',
                (f'Room {app.assigned_room} has been assigned.' if app.status == 'approved' and app.assigned_room
                 else f'Your hostel application status is now {app.get_status_display()}.'),
                level='success' if app.status == 'approved' else 'info',
                url='/hostel/',
            )
            messages.success(request, 'Application updated.')
            return redirect('hostel-manage')
    else:
        initial = {'assigned_room': app.recommended_room} if app.recommended_room and not app.assigned_room else None
        form = AssignRoomForm(instance=app, initial=initial)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Review — {app.student.full_name}', 'cancel_url': '/hostel/manage/'})


@admin_required
def room_list(request):
    rooms = Room.objects.select_related('hostel').order_by('hostel__name', 'block', 'number')
    return render(request, 'hostel/rooms.html', {'rooms': rooms})


@admin_required
def room_add(request):
    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Room added.')
            return redirect('hostel-rooms')
    else:
        form = RoomForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Room', 'cancel_url': '/hostel/rooms/'})


@admin_required
def hostel_list(request):
    hostels = Hostel.objects.all()
    return render(request, 'hostel/hostel-list.html', {'hostels': hostels})


@admin_required
def hostel_add(request):
    if request.method == 'POST':
        form = HostelForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Hostel added.')
            return redirect('hostel-list')
    else:
        form = HostelForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Hostel', 'cancel_url': '/hostel/hostels/'})


@office_staff_required
def run_recommendations(request):
    """Suggest a room for every pending application (POST). Approval stays manual."""
    from .services import HostelRecommendationService
    if request.method == 'POST':
        results = HostelRecommendationService.recommend_pending()
        matched = sum(1 for _, room, _ in results if room)
        messages.success(request, f'Recommendations updated: {matched} of {len(results)} pending applications have a suggested room.')
    return redirect('hostel-manage')
