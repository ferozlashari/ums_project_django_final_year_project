from django.db import models
from django.contrib.auth.models import User


class AttendanceSession(models.Model):
    """One real teaching/attendance event for one registered course section."""
    ATTENDANCE_TYPE_CHOICES = [
        ('physical', 'Physical Class'),
        ('online', 'Online Class'),
        ('hybrid', 'Hybrid'),
        ('qr', 'QR Check-in'),
        ('biometric', 'Biometric Verification'),
    ]
    section = models.ForeignKey('academics.CourseSection', on_delete=models.CASCADE, related_name='attendance_sessions')
    semester = models.ForeignKey('academics.Semester', on_delete=models.CASCADE, related_name='attendance_sessions')
    date = models.DateField()
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    attendance_type = models.CharField(max_length=20, choices=ATTENDANCE_TYPE_CHOICES, default='physical')
    topic = models.CharField(max_length=255, blank=True)
    is_open = models.BooleanField(default=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['section', 'semester', 'date']),
            models.Index(fields=['semester', 'date']),
        ]

    def __str__(self):
        return f'{self.section} — {self.date} — {self.get_attendance_type_display()}'


class AttendanceRecord(models.Model):
    METHOD_CHOICES = [
        ('manual', 'Marked by Teacher'),
        ('self_checkin', 'Self Check-In (Smart Attendance)'),
        ('biometric_webauthn', 'Passkey Verified (Smart Attendance)'),
        ('biometric_fingerprint', 'Physical Fingerprint Device'),
        ('biometric_face', 'Physical Face Recognition Device'),
        ('biometric_rfid', 'Physical RFID Card Reader'),
    ]
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='attendance_records')
    section = models.ForeignKey('academics.CourseSection', on_delete=models.SET_NULL, null=True, blank=True, related_name='attendance_records')
    semester = models.ForeignKey('academics.Semester', on_delete=models.SET_NULL, null=True, blank=True, related_name='attendance_records')
    session = models.ForeignKey(AttendanceSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='records')
    registration = models.ForeignKey('academics.CourseRegistration', on_delete=models.SET_NULL, null=True, blank=True, related_name='attendance_records')
    date = models.DateField()
    present = models.BooleanField(default=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    method = models.CharField(max_length=25, choices=METHOD_CHOICES, default='manual')
    remarks = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Attendance Record'
        verbose_name_plural = 'Attendance Records'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'section', 'date'],
                condition=models.Q(section__isnull=False),
                name='uniq_student_section_attendance_day',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'date']),
            models.Index(fields=['section', 'date']),
            models.Index(fields=['student', 'semester']),
            models.Index(fields=['registration', 'date']),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.registration_id:
            if self.registration.student_id != self.student_id:
                raise ValidationError('Attendance registration does not belong to this student.')
            if self.section_id and self.registration.section_id != self.section_id:
                raise ValidationError('Attendance registration does not belong to this section.')
            if self.semester_id and self.registration.semester_id != self.semester_id:
                raise ValidationError('Attendance registration does not belong to this semester.')
        if self.session_id:
            if self.section_id and self.session.section_id != self.section_id:
                raise ValidationError('Attendance session does not belong to this section.')
            if self.semester_id and self.session.semester_id != self.semester_id:
                raise ValidationError('Attendance session does not belong to this semester.')

    def __str__(self):
        return f"{self.student} - {self.date} - {'Present' if self.present else 'Absent'}"

    @property
    def duration_display(self):
        if self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            return f'{hours}h {minutes}m'
        return None


class AttendanceCorrectionRequest(models.Model):
    """A teacher's request to reopen finalised attendance.

    Finalised (closed) attendance cannot be edited by the teacher. They file this
    request with a reason; an authorised officer (Attendance 'approve' permission,
    or a Super Admin) approves - which reopens the session for editing - or rejects
    it with a note. Nothing about the original records changes until the teacher
    re-saves after approval, and every decision is audited.
    """
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    session = models.ForeignKey('AttendanceSession', on_delete=models.CASCADE, related_name='correction_requests')
    requested_by = models.ForeignKey('auth.User', on_delete=models.PROTECT, related_name='attendance_correction_requests')
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    decided_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Correction for {self.session} ({self.status})'
