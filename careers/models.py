from django.db import models
from django.contrib.auth.models import User


class Employer(models.Model):
    """A company/organization posting jobs or internships. Kept as its own
    record (rather than free-text on the posting) so the directory the
    proposal asks for actually lists distinct employers."""
    name = models.CharField(max_length=200)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class JobPosting(models.Model):
    TYPE_CHOICES = [('job', 'Full-time Job'), ('internship', 'Internship'), ('part_time', 'Part-time')]

    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='postings')
    title = models.CharField(max_length=200)
    posting_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='job')
    description = models.TextField()
    # Loose text match against a student's program/major, used for simple
    # keyword-based matching - e.g. "Computer Science, Software Engineering".
    relevant_majors = models.CharField(max_length=300, blank=True, help_text='Comma-separated majors/programs this role suits, e.g. "Computer Science, IT"')
    location = models.CharField(max_length=150, blank=True)
    application_deadline = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-posted_at']

    def __str__(self):
        return f'{self.title} @ {self.employer.name}'

    @property
    def is_open(self):
        from django.utils import timezone
        if not self.is_active:
            return False
        if self.application_deadline and self.application_deadline < timezone.now().date():
            return False
        return True


class JobApplication(models.Model):
    STATUS_CHOICES = [('submitted', 'Submitted'), ('shortlisted', 'Shortlisted'), ('rejected', 'Rejected'), ('hired', 'Hired')]

    posting = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='applications')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='job_applications')
    cover_note = models.TextField(max_length=1500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('posting', 'student')]
        ordering = ['-applied_at']

    def __str__(self):
        return f'{self.student.full_name} -> {self.posting.title} ({self.status})'


class ResumeProfile(models.Model):
    """A simple, self-service resume the built-in AI assistant can also read
    from when suggesting job matches. Deliberately plain-text/structured
    rather than file upload, so it's searchable and works without a file
    parser."""
    student = models.OneToOneField('registration.Student', on_delete=models.CASCADE, related_name='resume_profile')
    headline = models.CharField(max_length=200, blank=True, help_text='e.g. "Final-year CS student, backend focus"')
    summary = models.TextField(blank=True)
    skills = models.CharField(max_length=500, blank=True, help_text='Comma-separated, e.g. "Python, Django, SQL"')
    experience = models.TextField(blank=True, help_text='Internships, projects, part-time work - one per line')
    education_notes = models.TextField(blank=True)
    links = models.CharField(max_length=500, blank=True, help_text='LinkedIn/GitHub/portfolio URLs, comma-separated')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Resume - {self.student.full_name}'
