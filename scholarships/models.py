from django.db import models


class Scholarship(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    eligibility_criteria = models.TextField(blank=True)
    application_deadline = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    total_seats = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Maximum number of students who can hold this scholarship at once. Leave blank for unlimited.')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def seats_filled(self):
        return self.applications.filter(status='approved').count()

    @property
    def seats_available(self):
        if self.total_seats is None:
            return None
        return max(0, self.total_seats - self.seats_filled)

    def __str__(self):
        return self.name


class ScholarshipApplication(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    scholarship = models.ForeignKey(Scholarship, on_delete=models.CASCADE, related_name='applications')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='scholarship_applications')
    statement = models.TextField(blank=True, help_text='Briefly explain why you qualify.')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(auto_now_add=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('scholarship', 'student')

    def __str__(self):
        return f'{self.student.full_name} -> {self.scholarship.name}'
