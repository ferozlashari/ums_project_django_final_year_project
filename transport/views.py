from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Vehicle, Route, RouteStop, StudentTransportAssignment
from .forms import VehicleForm, RouteForm, RouteStopForm, AssignTransportForm
from core.permissions import admin_required, user_role
from core.models import notify


@login_required
def my_transport(request):
    """Student's own bus route, pickup point and time - the exact
    'What is my bus route?' answer the AI assistant also needs to give."""
    assignment = None
    if user_role(request.user) == 'student':
        try:
            student = request.user.student_profile
            assignment = StudentTransportAssignment.objects.select_related('route', 'stop', 'route__vehicle').filter(
                student=student, is_active=True,
            ).first()
        except Exception:
            pass
    return render(request, 'transport/my-transport.html', {'assignment': assignment})


@admin_required
def route_list(request):
    routes = Route.objects.select_related('vehicle').prefetch_related('stops').all()
    return render(request, 'transport/route-list.html', {'routes': routes})


@admin_required
def route_add(request):
    if request.method == 'POST':
        form = RouteForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Route created.')
            return redirect('transport-route-list')
    else:
        form = RouteForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Route', 'cancel_url': '/transport/routes/'})


@admin_required
def stop_add(request):
    if request.method == 'POST':
        form = RouteStopForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Stop added.')
            return redirect('transport-route-list')
    else:
        form = RouteStopForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Stop', 'cancel_url': '/transport/routes/'})


@admin_required
def vehicle_list(request):
    vehicles = Vehicle.objects.all()
    return render(request, 'transport/vehicle-list.html', {'vehicles': vehicles})


@admin_required
def vehicle_add(request):
    if request.method == 'POST':
        form = VehicleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Vehicle added.')
            return redirect('transport-vehicle-list')
    else:
        form = VehicleForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Vehicle', 'cancel_url': '/transport/vehicles/'})


@admin_required
def assignment_list(request):
    assignments = StudentTransportAssignment.objects.select_related('student', 'route', 'stop').filter(is_active=True)
    return render(request, 'transport/assignment-list.html', {'assignments': assignments})


@admin_required
def assign_transport(request):
    if request.method == 'POST':
        form = AssignTransportForm(request.POST)
        if form.is_valid():
            from registration.models import Student
            student = Student.objects.get(admission_no=form.cleaned_data['admission_no'])
            assignment, _ = StudentTransportAssignment.objects.update_or_create(
                student=student,
                defaults={'route': form.cleaned_data['route'], 'stop': form.cleaned_data.get('stop'), 'is_active': True},
            )
            notify(
                student.user, f'Transport assigned: {assignment.route.name}',
                f'Pickup at {assignment.stop.name if assignment.stop else "TBA"} - {assignment.stop.pickup_time.strftime("%H:%M") if assignment.stop else ""}',
                level='info', url='/transport/',
            )
            messages.success(request, f'{student.full_name} assigned to {assignment.route.name}.')
            return redirect('transport-assignment-list')
    else:
        form = AssignTransportForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Assign Student to Route', 'cancel_url': '/transport/assignments/'})


@admin_required
def bulk_assign_transport(request):
    """Assign many students to the same route/stop in one submission,
    instead of the admission-number-at-a-time form above. Paste/type
    admission numbers one per line (or comma-separated) - each is looked
    up and assigned independently, so one typo or unknown admission
    number doesn't block the rest of the batch; it's simply reported
    back as skipped, the same way the other bulk/automation workflows in
    this project report per-item results instead of all-or-nothing."""
    from registration.models import Student

    routes = Route.objects.filter(is_active=True).prefetch_related('stops')
    results = None

    if request.method == 'POST':
        route_id = request.POST.get('route')
        stop_id = request.POST.get('stop') or None
        raw_numbers = request.POST.get('admission_numbers', '')

        route = Route.objects.filter(pk=route_id).first()
        stop = RouteStop.objects.filter(pk=stop_id, route_id=route_id).first() if stop_id else None

        # Accept admission numbers separated by newlines, commas, or both.
        admission_nos = [
            n.strip() for chunk in raw_numbers.replace(',', '\n').splitlines()
            if (n := chunk.strip())
        ]

        assigned, skipped = [], []
        if not route:
            messages.error(request, 'Choose a route.')
        elif not admission_nos:
            messages.error(request, 'Enter at least one admission number.')
        else:
            for admission_no in admission_nos:
                student = Student.objects.filter(admission_no__iexact=admission_no).first()
                if not student:
                    skipped.append((admission_no, 'No student with that admission number.'))
                    continue
                assignment, _ = StudentTransportAssignment.objects.update_or_create(
                    student=student,
                    defaults={'route': route, 'stop': stop, 'is_active': True},
                )
                notify(
                    student.user, f'Transport assigned: {route.name}',
                    f'Pickup at {stop.name if stop else "TBA"} - {stop.pickup_time.strftime("%H:%M") if stop else ""}',
                    level='info', url='/transport/',
                )
                assigned.append(student)

            results = {'assigned': assigned, 'skipped': skipped, 'route': route, 'stop': stop}
            if assigned:
                messages.success(request, f'{len(assigned)} student(s) assigned to {route.name}.')
            if skipped:
                messages.warning(request, f'{len(skipped)} admission number(s) skipped - see details below.')

    return render(request, 'transport/bulk-assign.html', {'routes': routes, 'results': results})


@admin_required
@require_POST
def unassign_transport(request, pk):
    assignment = get_object_or_404(StudentTransportAssignment, pk=pk)
    assignment.is_active = False
    assignment.save(update_fields=['is_active'])
    messages.success(request, 'Student removed from route.')
    return redirect('transport-assignment-list')


@admin_required
def recommendations(request):
    """Recommended route/stop per unassigned student. Admin verification =
    clicking Approve on a row (POST); nothing is assigned automatically."""
    from registration.models import Student
    from .services import TransportRecommendationService
    from django.contrib import messages as msgs
    from django.shortcuts import redirect
    if request.method == 'POST':
        student = get_object_or_404(Student, pk=request.POST.get('student'))
        route, stop, reason = TransportRecommendationService.recommend(student)
        if route is None:
            msgs.error(request, f'Cannot assign {student.full_name}: {reason}')
        else:
            StudentTransportAssignment.objects.update_or_create(student=student, defaults={'route': route, 'stop': stop, 'is_active': True})
            msgs.success(request, f'{student.full_name} assigned to {route.name} ({stop.name}).')
        return redirect('transport-recommendations')
    return render(request, 'transport/recommendations.html', {'rows': TransportRecommendationService.recommendations()})
