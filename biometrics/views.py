from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import BiometricProviderConfig, BiometricVerificationEvent, ExamAttendance, OnlineClassAttendance
from core.permissions import admin_required, user_role, webauthn_recently_verified


@login_required
@require_POST
def verify_exam_attendance(request, exam_id):
    """Identity verification for sitting an exam - a passkey/WebAuthn
    check performed entirely on the student's own device (fingerprint,
    Face ID, Windows Hello, a security key, or a PIN); the server only
    ever sees a cryptographic verification result, never any biometric
    data."""
    from exams.models import ExamSession
    exam = get_object_or_404(ExamSession, pk=exam_id)
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students verify their own exam attendance.')
    if not webauthn_recently_verified(request):
        messages.error(request, 'Passkey verification failed or expired - please try again.')
        return redirect('exams')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('exams')
    ExamAttendance.objects.get_or_create(exam=exam, student=student, defaults={'method': 'webauthn'})
    messages.success(request, f'✅ Identity verified for {exam}.')
    return redirect('exams')


@login_required
@require_POST
def verify_online_class_join(request, pk):
    """Same passkey/WebAuthn identity check as exam attendance, applied
    to joining a live online class - so attendance can't simply be
    claimed by anyone who has the room link."""
    from onlineclass.models import OnlineClass
    oc = get_object_or_404(OnlineClass, pk=pk)
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students verify their own class attendance.')
    if not webauthn_recently_verified(request):
        messages.error(request, 'Passkey verification failed or expired - please try again.')
        return redirect('class-join', pk=pk)
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('class-join', pk=pk)
    from academics.models import CourseRegistration
    reg = CourseRegistration.objects.filter(student=student, section=oc.section, status='registered', semester=oc.semester).first()
    if not reg:
        raise PermissionDenied('You are not registered in this section for this semester.')
    OnlineClassAttendance.objects.get_or_create(online_class=oc, student=student, defaults={'method': 'webauthn', 'registration': reg})
    messages.success(request, '✅ Identity verified - attendance recorded for this class.')
    return redirect('class-join', pk=pk)


@admin_required
def command_center(request):
    """Biometric Command Center: real configured devices with a live/offline
    status derived from last_seen_at, and today's verification event
    totals by result. Shows an empty state when nothing is configured."""
    from django.utils import timezone
    devices = BiometricProviderConfig.objects.select_related('campus').order_by('provider_type', 'name')
    online_cutoff = timezone.now() - timezone.timedelta(minutes=15)
    device_rows = [{
        'device': d,
        'status': 'online' if (d.is_enabled and d.last_seen_at and d.last_seen_at >= online_cutoff) else
                  ('never_seen' if not d.last_seen_at else 'offline') if d.is_enabled else 'disabled',
    } for d in devices]
    today = timezone.localdate()
    todays_events = BiometricVerificationEvent.objects.filter(captured_at__date=today)
    event_counts = {choice: todays_events.filter(result=choice).count() for choice, _ in BiometricVerificationEvent.RESULT_CHOICES}
    return render(request, 'biometrics/command_center.html', {
        'device_rows': device_rows, 'event_counts': event_counts, 'total_devices': devices.count(),
    })
