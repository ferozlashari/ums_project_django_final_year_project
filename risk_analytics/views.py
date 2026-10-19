from django.views.decorators.http import require_POST
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .models import RiskFlag
from .scoring import recalculate_risk_flags
from core.permissions import staff_or_admin_required, user_role, section_scope_students


@staff_or_admin_required
def retention_dashboard(request):
    """Early-warning / retention dashboard. Admin sees every flagged
    student; faculty/staff only see flags for students actually enrolled
    in a section they teach - matching the subject-only scoping used
    everywhere else a teacher looks at student data."""
    flags = RiskFlag.objects.filter(is_resolved=False).select_related('student', 'student__program')
    if user_role(request.user) in ('faculty', 'staff'):
        from registration.models import Student
        my_students = section_scope_students(request.user, Student.objects.all())
        flags = flags.filter(student__in=my_students)
    return render(request, 'risk_analytics/dashboard.html', {'flags': flags})


@staff_or_admin_required
def recalculate_now(request):
    result = recalculate_risk_flags()
    messages.success(request, f"Recalculated: {result['scanned']} students scanned, {result['newly_high_risk']} newly high-risk.")
    return redirect('retention-dashboard')


@staff_or_admin_required
@require_POST
def resolve_flag(request, pk):
    flag = get_object_or_404(RiskFlag, pk=pk)
    flag.is_resolved = True
    flag.save(update_fields=['is_resolved'])
    messages.success(request, f'Marked {flag.student.full_name} as reviewed.')
    return redirect('retention-dashboard')
