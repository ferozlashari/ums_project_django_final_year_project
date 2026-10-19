from django.db import models
from django.contrib.auth.models import User


class GuardianLink(models.Model):
    """Connects a parent/guardian account to one student record. Admin must
    verify the link (upload/confirm a relationship in person or via the
    admissions record) before the guardian portal shows any data - this is
    the only thing stopping anyone from typing in a random admission number
    and reading someone else's child's attendance, fees, and grades."""
    RELATION_CHOICES = [('father', 'Father'), ('mother', 'Mother'), ('guardian', 'Guardian/Other')]

    guardian = models.ForeignKey(User, on_delete=models.CASCADE, related_name='guardian_links')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='guardian_links')
    relation = models.CharField(max_length=20, choices=RELATION_CHOICES, default='guardian')
    is_verified = models.BooleanField(default=False, help_text='Only verified links can view the student\'s data.')
    requested_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        unique_together = [('guardian', 'student')]
        ordering = ['-requested_at']

    def __str__(self):
        status = 'verified' if self.is_verified else 'pending'
        return f'{self.guardian.username} -> {self.student.full_name} ({status})'
