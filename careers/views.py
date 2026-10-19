from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Employer, JobPosting, JobApplication, ResumeProfile
from .forms import EmployerForm, JobPostingForm, JobApplicationForm, ResumeProfileForm
from core.permissions import staff_or_admin_required, user_role
from core.models import notify


def _own_student(user):
    try:
        return user.student_profile
    except Exception:
        return None


@login_required
def job_list(request):
    """Job/internship board. Students see a simple relevance hint (their
    program name matched against relevant_majors) but everyone open can see
    every active posting - matching a normal public job board."""
    postings = JobPosting.objects.filter(is_active=True).select_related('employer')
    q = request.GET.get('q', '').strip()
    if q:
        postings = postings.filter(title__icontains=q) | postings.filter(employer__name__icontains=q) | postings.filter(relevant_majors__icontains=q)

    student = _own_student(request.user)
    applied_ids = set()
    if student:
        applied_ids = set(JobApplication.objects.filter(student=student).values_list('posting_id', flat=True))

    return render(request, 'careers/job-list.html', {
        'postings': postings.distinct(), 'q': q, 'applied_ids': applied_ids, 'student': student,
    })


@login_required
def job_apply(request, pk):
    posting = get_object_or_404(JobPosting, pk=pk, is_active=True)
    student = _own_student(request.user)
    if student is None:
        raise PermissionDenied('Only students can apply for postings.')
    if JobApplication.objects.filter(posting=posting, student=student).exists():
        messages.info(request, 'You already applied to this posting.')
        return redirect('job-list')
    if request.method == 'POST':
        form = JobApplicationForm(request.POST)
        if form.is_valid():
            app = form.save(commit=False)
            app.posting = posting
            app.student = student
            app.save()
            messages.success(request, f'Application submitted for {posting.title}.')
            return redirect('my-job-applications')
    else:
        form = JobApplicationForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Apply — {posting.title}', 'cancel_url': '/careers/'})


@login_required
def my_applications(request):
    student = _own_student(request.user)
    apps = JobApplication.objects.filter(student=student).select_related('posting', 'posting__employer') if student else JobApplication.objects.none()
    return render(request, 'careers/my-applications.html', {'applications': apps})


@login_required
def my_resume(request):
    student = _own_student(request.user)
    if student is None:
        raise PermissionDenied('Only students can build a resume here.')
    profile, _ = ResumeProfile.objects.get_or_create(student=student)
    if request.method == 'POST':
        form = ResumeProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Resume saved.')
            return redirect('my-resume')
    else:
        form = ResumeProfileForm(instance=profile)
    return render(request, 'careers/my-resume.html', {'form': form, 'profile': profile})


@staff_or_admin_required
def manage_postings(request):
    postings = JobPosting.objects.select_related('employer').all()
    return render(request, 'careers/manage-postings.html', {'postings': postings})


@staff_or_admin_required
def posting_add(request):
    if request.method == 'POST':
        form = JobPostingForm(request.POST)
        if form.is_valid():
            posting = form.save(commit=False)
            posting.posted_by = request.user
            posting.save()
            messages.success(request, 'Posting published.')
            return redirect('manage-postings')
    else:
        form = JobPostingForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Job/Internship Posting', 'cancel_url': '/careers/manage/'})


@staff_or_admin_required
def employer_add(request):
    if request.method == 'POST':
        form = EmployerForm(request.POST)
        if form.is_valid():
            employer = form.save(commit=False)
            employer.added_by = request.user
            employer.save()
            messages.success(request, f'{employer.name} added to the employer directory.')
            return redirect('manage-postings')
    else:
        form = EmployerForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Add Employer', 'cancel_url': '/careers/manage/'})


@staff_or_admin_required
def posting_applications(request, pk):
    posting = get_object_or_404(JobPosting, pk=pk)
    apps = posting.applications.select_related('student')
    return render(request, 'careers/posting-applications.html', {'posting': posting, 'applications': apps})


@staff_or_admin_required
@require_POST
def update_application_status(request, pk):
    app = get_object_or_404(JobApplication, pk=pk)
    status = request.POST.get('status')
    if status in dict(JobApplication.STATUS_CHOICES):
        app.status = status
        app.save(update_fields=['status'])
        notify(
            app.student.user, f'Application update: {app.posting.title}',
            f'Your application status is now {app.get_status_display()}.',
            level='success' if status in ('shortlisted', 'hired') else 'info',
            url='/careers/my-applications/',
        )
        messages.success(request, f'Marked {app.get_status_display()}.')
    return redirect('posting-applications', pk=app.posting_id)
