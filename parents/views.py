from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import GuardianLink
from .forms import GuardianLinkRequestForm
from core.permissions import role_required, admin_required
from core.models import notify


@role_required('guardian')
def guardian_dashboard(request):
    """Read-only view for a verified parent/guardian: attendance %, unpaid
    fees, and latest results for each linked, verified student. Nothing
    here can be edited - this portal only ever displays data, matching the
    proposal's 'read-only view for parents/guardians' scope."""
    links = GuardianLink.objects.filter(guardian=request.user, is_verified=True).select_related('student', 'student__program')
    pending_links = GuardianLink.objects.filter(guardian=request.user, is_verified=False).select_related('student')

    children_data = []
    for link in links:
        student = link.student
        from attendance.models import AttendanceRecord
        from finance.models import Invoice
        from exams.models import GradeEntry

        total = AttendanceRecord.objects.filter(student=student).count()
        present = AttendanceRecord.objects.filter(student=student, present=True).count()
        attendance_pct = round((present / total) * 100, 1) if total else None
        unpaid_invoices = Invoice.objects.filter(student=student, paid=False)
        unpaid_total = sum((inv.amount for inv in unpaid_invoices), start=0)
        recent_grades = GradeEntry.objects.filter(student=student).select_related('exam').order_by('-id')[:5]

        children_data.append({
            'link': link, 'student': student, 'attendance_pct': attendance_pct,
            'unpaid_invoices': unpaid_invoices, 'unpaid_total': unpaid_total,
            'recent_grades': recent_grades,
        })

    return render(request, 'parents/dashboard.html', {
        'children_data': children_data, 'pending_links': pending_links,
    })


@login_required
def request_link(request):
    """Any signed-in guardian account can request a link to a student by
    admission number; it stays invisible/unverified until admin approves it."""
    if request.method == 'POST':
        form = GuardianLinkRequestForm(request.POST)
        if form.is_valid():
            from registration.models import Student
            student = Student.objects.get(admission_no=form.cleaned_data['admission_no'])
            link, created = GuardianLink.objects.get_or_create(
                guardian=request.user, student=student,
                defaults={'relation': form.cleaned_data['relation']},
            )
            if not created:
                messages.info(request, 'You already have a link request for this student.')
            else:
                messages.success(request, 'Request submitted. An admin will verify it before you can view data.')
            return redirect('guardian-dashboard')
    else:
        form = GuardianLinkRequestForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Link to a Student', 'cancel_url': '/parents/'})


@admin_required
def manage_links(request):
    """Admin queue to verify or reject guardian-to-student link requests."""
    pending = GuardianLink.objects.filter(is_verified=False).select_related('guardian', 'student')
    verified = GuardianLink.objects.filter(is_verified=True).select_related('guardian', 'student')
    return render(request, 'parents/manage-links.html', {'pending': pending, 'verified': verified})


@admin_required
@require_POST
def verify_link(request, pk):
    link = get_object_or_404(GuardianLink, pk=pk)
    link.is_verified = True
    link.verified_at = timezone.now()
    link.verified_by = request.user
    link.save(update_fields=['is_verified', 'verified_at', 'verified_by'])
    notify(
        link.guardian, 'Guardian access approved',
        f'You can now view {link.student.full_name}\'s attendance, fees and results.',
        level='success', url='/parents/',
    )
    messages.success(request, 'Link verified.')
    return redirect('manage-guardian-links')


@admin_required
@require_POST
def reject_link(request, pk):
    link = get_object_or_404(GuardianLink, pk=pk)
    link.delete()
    messages.success(request, 'Link request removed.')
    return redirect('manage-guardian-links')
