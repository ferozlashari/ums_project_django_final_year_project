from django.db import models


class RiskFlag(models.Model):
    """A computed early-warning flag for one student, refreshed by
    recalculate_risk_flags() (run via the 'Recalculate Now' button or the
    flag_at_risk_students management command). This formalizes attendance-
    and GPA-based risk scoring into a persisted, reviewable record rather
    than a number computed silently on every page load, so advisors can see
    when a flag first appeared and mark it resolved once handled.
    """
    LEVEL_CHOICES = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]

    student = models.OneToOneField('registration.Student', on_delete=models.CASCADE, related_name='risk_flag')
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='low')
    attendance_pct = models.FloatField(null=True, blank=True)
    average_percentage = models.FloatField(null=True, blank=True)
    failed_courses_count = models.PositiveSmallIntegerField(default=0, help_text='Distinct courses with a failing (F) grade on the latest attempt.')
    has_outstanding_fees = models.BooleanField(default=False)
    reasons = models.TextField(blank=True, help_text='Human-readable reasons this student was flagged.')
    is_resolved = models.BooleanField(default=False, help_text='Advisor has reviewed/handled this flag.')
    first_flagged_at = models.DateTimeField(auto_now_add=True)
    last_computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-level', '-last_computed_at']

    def __str__(self):
        return f'{self.student.full_name} - {self.get_level_display()} risk'
