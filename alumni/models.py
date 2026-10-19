from django.db import models
from django.contrib.auth.models import User


class AlumniProfile(models.Model):
    """A directory entry for a graduated student. Kept separate from
    registration.Student (rather than adding fields there) because alumni
    data - employer, industry, mentorship availability - is voluntary,
    self-maintained, and grows long after the academic record is closed.
    """
    student = models.OneToOneField(
        'registration.Student', on_delete=models.CASCADE, related_name='alumni_profile',
        help_text='Must be a graduated student record.',
    )
    graduation_year = models.PositiveIntegerField()
    current_employer = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    industry = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, default='Pakistan')
    linkedin_url = models.URLField(blank=True)
    bio = models.TextField(blank=True, help_text='A short note for the directory - career path, advice, what you studied.')
    willing_to_mentor = models.BooleanField(default=False, help_text='Show a "Request mentorship" button to current students.')
    is_public = models.BooleanField(default=True, help_text='Show this profile in the alumni directory. Turn off to stay listed only to admin.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-graduation_year', 'student__full_name']

    def __str__(self):
        return f'{self.student.full_name} ({self.graduation_year})'


class MentorshipRequest(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined')]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mentorship_requests_sent')
    alumni = models.ForeignKey(AlumniProfile, on_delete=models.CASCADE, related_name='mentorship_requests')
    message = models.TextField(max_length=800)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student.username} -> {self.alumni} ({self.status})'
