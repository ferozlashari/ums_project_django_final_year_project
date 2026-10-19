from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404

from .models import AlumniProfile, MentorshipRequest
from .forms import AlumniProfileForm, MentorshipRequestForm
from core.permissions import user_role, admin_required
from core.models import notify


def _own_graduated_student(user):
    """Return the requesting user's Student record if it exists and has
    graduated, else None. Only a graduated student's own account may create
    or edit an AlumniProfile - this keeps the directory self-service without
    letting anyone claim someone else's record."""
    try:
        student = user.student_profile
    except Exception:
        return None
    return student if student.status == 'graduated' else None


@login_required
def directory(request):
    """Alumni directory - visible to every signed-in role. Only public
    profiles are listed; admins additionally see private ones."""
    profiles = AlumniProfile.objects.select_related('student', 'student__program').all()
    if user_role(request.user) != 'admin':
        profiles = profiles.filter(is_public=True)

    q = request.GET.get('q', '').strip()
    year = request.GET.get('year', '').strip()
    if q:
        profiles = (
            profiles.filter(current_employer__icontains=q)
            | profiles.filter(industry__icontains=q)
            | profiles.filter(student__full_name__icontains=q)
        )
    if year:
        profiles = profiles.filter(graduation_year=year)

    return render(request, 'alumni/directory.html', {
        'profiles': profiles.distinct(), 'q': q, 'year': year,
        'my_profile': AlumniProfile.objects.filter(student__user=request.user).first(),
        'can_join': _own_graduated_student(request.user) is not None,
    })


@login_required
def my_profile(request):
    """Create or edit the signed-in graduated student's own alumni listing."""
    student = _own_graduated_student(request.user)
    if student is None:
        raise PermissionDenied("Only graduated students can create an alumni profile.")

    profile, _created = AlumniProfile.objects.get_or_create(
        student=student, defaults={'graduation_year': getattr(student, 'graduation_year', None) or 2026},
    )
    if request.method == 'POST':
        form = AlumniProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your alumni profile is up to date.')
            return redirect('alumni-directory')
    else:
        form = AlumniProfileForm(instance=profile)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'My Alumni Profile', 'cancel_url': '/alumni/'})


@login_required
def request_mentorship(request, pk):
    alumni_profile = get_object_or_404(AlumniProfile, pk=pk, willing_to_mentor=True)
    if request.method == 'POST':
        form = MentorshipRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.student = request.user
            req.alumni = alumni_profile
            req.save()
            notify(
                alumni_profile.student.user, 'New mentorship request',
                f'{request.user.get_full_name() or request.user.username} requested mentorship.',
                level='info', url='/alumni/mentorship/requests/',
            )
            messages.success(request, 'Mentorship request sent.')
            return redirect('alumni-directory')
    else:
        form = MentorshipRequestForm()
    return render(request, 'core/form_base.html', {
        'form': form, 'title': f'Request mentorship from {alumni_profile}', 'cancel_url': '/alumni/',
    })


@login_required
def my_mentorship_requests(request):
    """Incoming requests for the signed-in alumnus to accept/decline."""
    alumni_profile = AlumniProfile.objects.filter(student__user=request.user).first()
    requests_qs = MentorshipRequest.objects.filter(alumni=alumni_profile).select_related('student') if alumni_profile else MentorshipRequest.objects.none()
    return render(request, 'alumni/mentorship-requests.html', {'requests': requests_qs})


@login_required
@require_POST
def respond_mentorship(request, pk):
    req = get_object_or_404(MentorshipRequest, pk=pk)
    if req.alumni.student.user_id != request.user.id:
        raise PermissionDenied("This isn't your mentorship request to respond to.")
    status = request.POST.get('status')
    if status in ('accepted', 'declined'):
        from django.utils import timezone
        req.status = status
        req.responded_at = timezone.now()
        req.save(update_fields=['status', 'responded_at'])
        notify(
            req.student, f'Mentorship request {status}',
            f'{req.alumni} {status} your mentorship request.',
            level='success' if status == 'accepted' else 'info', url='/alumni/',
        )
        messages.success(request, f'Request marked {status}.')
    return redirect('my-mentorship-requests')


@admin_required
def admin_alumni_list(request):
    """Admin oversight of every alumni record, public or private."""
    profiles = AlumniProfile.objects.select_related('student').all()
    return render(request, 'alumni/admin-list.html', {'profiles': profiles})
