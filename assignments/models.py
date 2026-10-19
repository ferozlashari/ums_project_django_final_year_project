from django.db import models

from core.upload_validators import validate_assignment_upload


class Assignment(models.Model):
    section = models.ForeignKey('academics.CourseSection', on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateTimeField()
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-due_date']

    def __str__(self):
        return f'{self.title} ({self.section})'

    @property
    def is_overdue(self):
        from django.utils import timezone
        return timezone.now() > self.due_date


class Submission(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='assignment_submissions')
    text_answer = models.TextField(blank=True)
    file = models.FileField(upload_to='assignment_submissions/%Y/%m/', blank=True, null=True, validators=[validate_assignment_upload])
    submitted_at = models.DateTimeField(auto_now_add=True)
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('assignment', 'student')]
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.student.full_name} -> {self.assignment.title}'

    @property
    def was_late(self):
        return self.submitted_at > self.assignment.due_date
