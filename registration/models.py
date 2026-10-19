from django.core.validators import RegexValidator
from django.db import models
from django.contrib.auth.models import User

from core.encrypted_fields import EncryptedCharField

cnic_validator = RegexValidator(
    regex=r'^\d{5}-\d{7}-\d{1}$',
    message='Enter CNIC in the format 12345-1234567-1 (13 digits with dashes).',
)

# Shared by Student and admissions.Application - domicile province, used
# for district-quota admission seats and for admin filtering/reporting.
PROVINCE_CHOICES = [
    ('punjab', 'Punjab'),
    ('sindh', 'Sindh'),
    ('kpk', 'Khyber Pakhtunkhwa'),
    ('balochistan', 'Balochistan'),
    ('gilgit_baltistan', 'Gilgit-Baltistan'),
    ('ajk', 'Azad Jammu & Kashmir'),
    ('islamabad', 'Islamabad Capital Territory'),
]


class Enrollment(models.Model):
    """Authoritative, historical record of which program (and curriculum
    version) a student belongs to. `Student.program` stays as a fast-read
    cache that Student.save() keeps in sync automatically - every change to
    it closes the previous Enrollment and opens a new one, so nothing else
    in the codebase has to change to gain audit history.

    `curriculum` is PINNED at enrollment time to whichever curriculum was
    active then, so a student's academic position/course list never shifts
    under them if the program's active curriculum version changes later.
    """
    STATUS_CHOICES = [('active', 'Active'), ('completed', 'Completed'),
                       ('transferred', 'Transferred'), ('withdrawn', 'Withdrawn')]
    student = models.ForeignKey('Student', on_delete=models.CASCADE, related_name='enrollments')
    program = models.ForeignKey('academics.Program', on_delete=models.CASCADE, related_name='enrollments')
    curriculum = models.ForeignKey('academics.Curriculum', on_delete=models.SET_NULL, null=True, blank=True, related_name='enrollments')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active')
    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-started_on', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['student'], condition=models.Q(status='active'), name='uniq_one_active_enrollment_per_student'),
        ]

    def __str__(self):
        return f'{self.student.full_name} -> {self.program} ({self.get_status_display()})'


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    full_name = models.CharField(max_length=255)
    admission_no = models.CharField(max_length=120, unique=True)
    # Compulsory identity document for admission, hostel, and fee records.
    # Kept optional at the database level (blank=True) so this update never
    # breaks existing student records that predate this field - it's
    # enforced as required in the registration/admission forms instead.
    cnic = EncryptedCharField(max_length=500, blank=True, validators=[cnic_validator], help_text='Format: 12345-1234567-1', verbose_name='CNIC / National ID')
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=100, blank=True, help_text='Domicile district - used for district-quota admission seats and admin reporting.')
    province = models.CharField(max_length=30, choices=PROVINCE_CHOICES, blank=True)
    GENDER_CHOICES = [('male', 'Male'), ('female', 'Female'), ('other', 'Other/Prefer not to say')]
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, help_text='Used to match gender-specific hostel availability.')
    program = models.ForeignKey('academics.Program', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=[('active','Active'),('graduated','Graduated'),('suspended','Suspended'),('withdrawn','Withdrawn')], default='active')
    # The institutional Semester this student was admitted in - the one
    # fact needed to compute "what year/semester of the degree are they
    # in right now" automatically (see current_academic_position below),
    # instead of a program/semester being assigned to a student by hand
    # every term. Left null for students who existed before this field
    # was added rather than guessed at - current_academic_position simply
    # reports itself unavailable for those, rather than showing a
    # possibly-wrong computed year.
    admission_semester = models.ForeignKey(
        'academics.Semester', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='The semester this student was first admitted in - used to automatically compute their current year/semester of study.',
    )

    @property
    def current_enrollment(self):
        """The authoritative active Enrollment row, or None."""
        if self.pk is None:
            return None
        return self.enrollments.filter(status='active').select_related('curriculum', 'program').first()

    @property
    def active_program(self):
        """The program the student is ACTUALLY enrolled in right now.

        Single source of truth for all academic, finance, registration and exam
        logic: resolved from the active Enrollment, never from the `program`
        column (which is only a display cache kept in sync by save())."""
        enrollment = self.current_enrollment
        return enrollment.program if enrollment else None

    @property
    def active_program_id(self):
        enrollment = self.current_enrollment
        return enrollment.program_id if enrollment else None

    def save(self, *args, **kwargs):
        """Keep the Enrollment history in sync whenever `program` changes -
        including edits made from /admin/ or a plain ModelForm, not just
        code that knows about Enrollment."""
        from django.utils import timezone
        is_new = self.pk is None
        old_program_id = None if is_new else (
            Student.objects.filter(pk=self.pk).values_list('program_id', flat=True).first())
        super().save(*args, **kwargs)
        if not self.program_id and old_program_id:
            # Program cleared: the enrollment is the source of truth, so close it.
            self.enrollments.filter(status='active').update(status='withdrawn', ended_on=timezone.localdate())
        if self.program_id and (is_new or old_program_id != self.program_id):
            today = timezone.localdate()
            self.enrollments.filter(status='active').update(status='transferred', ended_on=today)
            curriculum = self.program.curricula.filter(is_active=True).order_by('-version').first()
            Enrollment.objects.create(student=self, program_id=self.program_id, curriculum=curriculum,
                                      status='active', started_on=today)

    @property
    def current_academic_position(self):
        """Authoritative computed academic position.

        Curriculum-aware when a curriculum is configured; otherwise uses the
        student's recorded admission semester as a compatibility fallback.
        This keeps the UI automatic while never asking an administrator to
        manually edit a student's current year/semester every term.
        """
        from core.services.academic import AcademicEligibilityService
        return AcademicEligibilityService.academic_position(self)

    @property
    def cnic_display(self):
        """Safe-for-templates CNIC value. If FIELD_ENCRYPTION_KEY changed
        since this record was encrypted (e.g. an ephemeral auto-generated
        dev key was lost on redeploy), EncryptedCharField.from_db_value
        silently falls back to the still-encrypted ciphertext rather than
        raising - showing that raw blob to a user looks broken and leaks
        the ciphertext for no reason, so detect and mask it here instead
        of ever rendering it directly in a template."""
        if self.cnic and str(self.cnic).startswith('gAAAAA'):
            return '(unavailable - please re-enter your CNIC)'
        return self.cnic or ''

    def __str__(self): return self.full_name

