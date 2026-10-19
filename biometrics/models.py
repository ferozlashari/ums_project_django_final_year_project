from django.db import models
from django.contrib.auth.models import User


def _generate_api_key():
    """Kept only so historical migrations (which reference this as a
    field default for the now-removed BiometricDevice model) can still
    be loaded - physical biometric hardware support was removed from
    this app; nothing in the current models uses this anymore."""
    import secrets
    return secrets.token_urlsafe(32)


class ExamAttendance(models.Model):
    """Identity verification for sitting an exam, via the browser's
    WebAuthn/passkey flow - fingerprint, Face ID, Windows Hello, a
    security key, or a device PIN, entirely on the student's own device;
    the server only ever receives a cryptographic verification result,
    never raw biometric data. A manual invigilator override remains
    available for edge cases (e.g. no passkey registered, hardware
    failure)."""
    METHOD_CHOICES = [('webauthn', 'Passkey / Device Authentication'), ('manual', 'Manually Verified by Invigilator')]

    exam = models.ForeignKey('exams.ExamSession', on_delete=models.CASCADE, related_name='biometric_attendance')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='exam_attendance')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='webauthn')
    verified_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text='Invigilator, for manual verification.')

    class Meta:
        unique_together = [('exam', 'student')]
        ordering = ['-verified_at']

    def __str__(self):
        return f'{self.student.full_name} verified for {self.exam} ({self.get_method_display()})'


class OnlineClassAttendance(models.Model):
    """Identity-verified join record for a live online class - separate
    from simply clicking the Jitsi link, so attendance can't just be
    claimed by anyone with the room code. Verified the same way as exam
    attendance: passkey/WebAuthn, with a manual teacher override for
    edge cases."""
    METHOD_CHOICES = [('webauthn', 'Passkey / Device Authentication'), ('manual', 'Marked by Teacher')]

    online_class = models.ForeignKey('onlineclass.OnlineClass', on_delete=models.CASCADE, related_name='attendance')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='online_class_attendance')
    registration = models.ForeignKey('academics.CourseRegistration', on_delete=models.SET_NULL, null=True, blank=True, related_name='online_attendance')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='webauthn')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('online_class', 'student')]
        ordering = ['-joined_at']

    def __str__(self):
        return f'{self.student.full_name} joined {self.online_class.title}'


class BiometricProviderConfig(models.Model):
    """Vendor-neutral optional physical biometric integration.

    Raw fingerprint/face templates remain on the device/vendor platform.
    UMS stores only provider identity, device metadata and verification events.
    """
    PROVIDER_CHOICES = [('fingerprint','Fingerprint'),('face','Face'),('rfid','RFID'),('custom','Custom Vendor')]
    name = models.CharField(max_length=120)
    provider_type = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    endpoint = models.URLField(blank=True)
    device_identifier = models.CharField(max_length=120, unique=True)
    is_enabled = models.BooleanField(default=False)
    campus = models.ForeignKey('core.Campus', on_delete=models.SET_NULL, null=True, blank=True, related_name='biometric_devices')
    last_seen_at = models.DateTimeField(null=True, blank=True)
    config = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f'{self.name} ({self.get_provider_type_display()})'


class BiometricVerificationEvent(models.Model):
    RESULT_CHOICES = [('verified','Verified'),('rejected','Rejected'),('offline','Offline'),('manual','Manual Override')]
    provider = models.ForeignKey(BiometricProviderConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='biometric_events')
    section = models.ForeignKey('academics.CourseSection', on_delete=models.SET_NULL, null=True, blank=True, related_name='biometric_events')
    attendance_session = models.ForeignKey('attendance.AttendanceSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='biometric_events')
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    external_reference = models.CharField(max_length=200, blank=True)
    captured_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=['student','captured_at']), models.Index(fields=['section','captured_at'])]
