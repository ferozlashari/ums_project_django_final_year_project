from django.db import models
from django.contrib.auth.models import User
from registration.models import cnic_validator, PROVINCE_CHOICES
from core.encrypted_fields import EncryptedCharField
from core.upload_validators import validate_document_upload

class Application(models.Model):
    STATUS_CHOICES = [('pending','Pending'),('accepted','Accepted'),('rejected','Rejected'),('waitlist','Waitlist')]
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # Public applicants (not yet registered) fill these in directly.
    full_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    cnic = EncryptedCharField(max_length=500, blank=True, validators=[cnic_validator], help_text='Format: 12345-1234567-1', verbose_name='CNIC / National ID')
    program = models.ForeignKey('academics.Program', on_delete=models.CASCADE)
    ADMISSION_TYPE_CHOICES = [('open_merit', 'Open Merit'), ('district_quota', 'District Quota')]
    admission_type = models.CharField(max_length=20, choices=ADMISSION_TYPE_CHOICES, default='open_merit', help_text='Which seat pool this application counts against once accepted.')
    district = models.CharField(max_length=100, blank=True, help_text='Domicile district - used for district-quota admission seats and admin reporting.')
    province = models.CharField(max_length=30, choices=PROVINCE_CHOICES, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField(blank=True)
    previous_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='Percentage in the last qualification (0-100). Counts toward merit according to the merit weights in Site Settings.')

    # Required supporting documents for admission - kept blank=True/default=''
    # at the DB level so this migration never breaks pre-existing rows;
    # enforced as required in the actual application forms instead.
    cnic_copy = models.FileField(upload_to='admission_docs/cnic/%Y/%m/', blank=True, default='', validators=[validate_document_upload], help_text='Scanned copy of CNIC/B-Form (PDF/JPG/PNG, max 5MB).')
    education_certificate = models.FileField(upload_to='admission_docs/education/%Y/%m/', blank=True, default='', validators=[validate_document_upload], help_text='Most recent degree/certificate (Matric/Inter/Bachelor as applicable).')
    domicile_certificate = models.FileField(upload_to='admission_docs/domicile/%Y/%m/', null=True, blank=True, validators=[validate_document_upload], help_text='Domicile certificate, if required by your program/quota.')

    def __str__(self):
        who = self.applicant.username if self.applicant else (self.full_name or self.email or 'Guest')
        return f"{who} -> {self.program.code}"

    @property
    def cnic_display(self):
        """Same masking as Student.cnic_display - see that docstring."""
        if self.cnic and str(self.cnic).startswith('gAAAAA'):
            return '(unavailable - please re-enter your CNIC)'
        return self.cnic or ''

    @property
    def display_name(self):
        if self.applicant:
            return self.applicant.get_full_name() or self.applicant.username
        return self.full_name or self.email or 'Guest applicant'


class EntryTest(models.Model):
    """The compulsory admission entry test - scheduled by admin once an
    Application is submitted, then a single mark entry drives everything
    else automatically: pass (>49/100) flips the Application to Accepted
    and creates the Student record in the same action; fail flips it to
    Rejected. No separate manual 'now make them a student' step - entering
    the mark IS the decision point.
    """
    PASS_MARK = 49  # strictly greater than this to pass, per admission policy

    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='entry_test')
    roll_number = models.CharField(max_length=40, unique=True)
    test_date = models.DateField()
    test_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True, default='Main Campus Examination Hall')
    scheduled_at = models.DateTimeField(auto_now_add=True)
    scheduled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='Out of 100.')
    evaluated_at = models.DateTimeField(null=True, blank=True)
    evaluated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-scheduled_at']

    def __str__(self):
        return f'Entry test {self.roll_number} - {self.application.display_name}'

    @property
    def is_evaluated(self):
        return self.marks_obtained is not None

    @property
    def passed(self):
        if not self.is_evaluated:
            return None
        return float(self.marks_obtained) > self.PASS_MARK

class ProgramPreference(models.Model):
    """Up to 5 ranked program choices for one Application, used by the
    preference-based merit allocation (AdmissionService.run_preference_allocation).
    rank 1 is always kept equal to Application.program for backward
    compatibility with code that only knows about the single .program field.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('selected', 'Selected'),
        ('not_allocated', 'Not Allocated'), ('waiting_list', 'Waiting List'),
    ]
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='preferences')
    program = models.ForeignKey('academics.Program', on_delete=models.CASCADE, related_name='admission_preferences')
    rank = models.PositiveSmallIntegerField(help_text='1 = first choice, up to 5.')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    merit_rank_in_program = models.PositiveIntegerField(null=True, blank=True,
        help_text='This applicant\'s rank by merit score within this program+pool, after the last allocation run.')

    class Meta:
        ordering = ['rank']
        constraints = [
            models.UniqueConstraint(fields=['application', 'rank'], name='uniq_preference_rank_per_application'),
            models.UniqueConstraint(fields=['application', 'program'], name='uniq_preference_program_per_application'),
        ]

    def __str__(self):
        return f'{self.application} - #{self.rank} {self.program.code} ({self.get_status_display()})'
