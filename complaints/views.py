from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .models import Complaint
from .forms import ComplaintForm, ComplaintResponseForm
from core.permissions import staff_or_admin_required, user_role
from core.models import notify


@login_required
def submit_complaint(request):
    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.user = request.user
            c.save()
            messages.success(request, 'Complaint submitted. You can track its status below.')
            return redirect('my-complaints')
    else:
        form = ComplaintForm()
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Submit a Complaint', 'cancel_url': '/complaints/'})


@login_required
def my_complaints(request):
    complaints = Complaint.objects.filter(user=request.user)
    return render(request, 'complaints/my_complaints.html', {'complaints': complaints})


@staff_or_admin_required
def manage_complaints(request):
    complaints = Complaint.objects.select_related('user').all()
    status = request.GET.get('status', '')
    if status:
        complaints = complaints.filter(status=status)
    return render(request, 'complaints/manage.html', {'complaints': complaints, 'status': status})


@staff_or_admin_required
def respond_complaint(request, pk):
    complaint = get_object_or_404(Complaint, pk=pk)
    if request.method == 'POST':
        form = ComplaintResponseForm(request.POST, instance=complaint)
        if form.is_valid():
            form.save()
            notify(
                complaint.user, f'Complaint update: {complaint.subject}',
                f'Status changed to {complaint.get_status_display()}.',
                level='info', url='/complaints/',
            )
            messages.success(request, 'Complaint updated.')
            return redirect('manage-complaints')
    else:
        form = ComplaintResponseForm(instance=complaint)
    return render(request, 'core/form_base.html', {'form': form, 'title': f'Respond — {complaint.subject}', 'cancel_url': '/complaints/manage/'})
