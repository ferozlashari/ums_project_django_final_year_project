from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Scholarship, ScholarshipApplication
from .forms import ScholarshipForm, ScholarshipApplyForm
from core.permissions import staff_or_admin_required, user_role
from core.models import notify


@login_required
def scholarship_list(request):
    scholarships = Scholarship.objects.filter(active=True).order_by('application_deadline')
    my_application_ids = set()
    if user_role(request.user) == 'student':
        try:
            student = request.user.student_profile
            my_application_ids = set(ScholarshipApplication.objects.filter(student=student).values_list('scholarship_id', flat=True))
        except Exception:
            pass
    return render(request, 'scholarships/list.html', {
        'scholarships': scholarships, 'today': timezone.now().date(),
        'my_application_ids': my_application_ids, 'role': user_role(request.user),
    })


@login_required
def apply_scholarship(request, pk):
    scholarship = get_object_or_404(Scholarship, pk=pk, active=True)
    if user_role(request.user) != 'student':
        messages.error(request, 'Only students can apply for scholarships.')
        return redirect('scholarship-list')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('scholarship-list')

    if ScholarshipApplication.objects.filter(scholarship=scholarship, student=student).exists():
        messages.info(request, 'You already applied for this scholarship.')
        return redirect('my-scholarship-applications')

    if scholarship.total_seats is not None and scholarship.seats_available <= 0:
        messages.error(request, f'{scholarship.name} has no seats available right now ({scholarship.total_seats} filled).')
        return redirect('scholarship-list')

    if request.method == 'POST':
        form = ScholarshipApplyForm(request.POST)
        if form.is_valid():
            app = form.save(commit=False)
            app.scholarship = scholarship
            app.student = student
            app.save()
            messages.success(request, 'Scholarship application submitted.')
            return redirect('my-scholarship-applications')
    else:
        form = ScholarshipApplyForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Apply — {scholarship.name}', 'cancel_url': '/scholarships/'})


@login_required
def my_applications(request):
    try:
        student = request.user.student_profile
        applications = ScholarshipApplication.objects.filter(student=student).select_related('scholarship')
    except Exception:
        applications = ScholarshipApplication.objects.none()
    return render(request, 'scholarships/my_applications.html', {'applications': applications})


@staff_or_admin_required
def manage_scholarships(request):
    scholarships = Scholarship.objects.all().order_by('-created_at')
    return render(request, 'scholarships/manage.html', {'scholarships': scholarships})


@staff_or_admin_required
def scholarship_add(request):
    if request.method == 'POST':
        form = ScholarshipForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Scholarship created.')
            return redirect('manage-scholarships')
    else:
        form = ScholarshipForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Scholarship', 'cancel_url': '/scholarships/manage/'})


@staff_or_admin_required
def scholarship_applications(request, pk):
    scholarship = get_object_or_404(Scholarship, pk=pk)
    applications = scholarship.applications.select_related('student')
    return render(request, 'scholarships/applications.html', {'scholarship': scholarship, 'applications': applications})


@staff_or_admin_required
@require_POST
def review_scholarship_application(request, pk):
    app = get_object_or_404(ScholarshipApplication, pk=pk)
    status = request.POST.get('status')
    if status in dict(ScholarshipApplication.STATUS_CHOICES):
        if status == 'approved' and app.scholarship.total_seats is not None and app.scholarship.seats_available <= 0:
            messages.error(request, f'{app.scholarship.name} has no seats left ({app.scholarship.total_seats} filled). Reject or wait for a seat to free up before approving another.')
            return redirect('scholarship-applications', pk=app.scholarship_id)
        app.status = status
        app.save(update_fields=['status'])
        from core.models import log_action
        log_action(
            request.user, 'SCHOLARSHIP_APPLICATION_REVIEWED',
            obj=f'{app.student} / {app.scholarship}', changes={'status': ['pending', status]}, request=request,
        )
        notify(
            app.student.user, f'Scholarship application {app.get_status_display().lower()}',
            f'Your application for {app.scholarship.name} was {app.get_status_display().lower()}.',
            level='success' if status == 'approved' else 'warning',
            url='/scholarships/my-applications/',
        )
        messages.success(request, f'Application marked {app.get_status_display()}.')
    return redirect('scholarship-applications', pk=app.scholarship_id)
