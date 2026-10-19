from django.conf import settings
from django.db import models


class WorkflowRequest(models.Model):
    """A generic request -> review -> approve/reject -> apply -> audit
    pipeline for actions that shouldn't happen with a single unchecked
    click - e.g. a teacher asking to correct a locked mark, or an office
    admin asking to adjust a fee amount. This deliberately does NOT
    replace the existing dedicated approval flows that already exist for
    hostel/scholarship/retake applications - those already have their own
    domain-specific status fields and views. This is for the cases the
    spec calls out that had no queue at all: marks correction and fee
    adjustment, plus a generic "other" bucket for anything not yet worth
    a dedicated model.
    """
    TYPE_CHOICES = [
        ("marks_correction", "Marks Correction"),
        ("fee_adjustment", "Fee Adjustment"),
        ("refund", "Refund"),
        ("other", "Other / Registration Exception"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    request_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="workflow_requests"
    )
    # Optional links to the record this request is actually about - only
    # one of these will be set, depending on request_type.
    grade_entry = models.ForeignKey(
        "exams.GradeEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="workflow_requests"
    )
    invoice = models.ForeignKey(
        "finance.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="workflow_requests"
    )

    old_value = models.CharField(max_length=100, blank=True, help_text="Current value, for reference.")
    new_value = models.CharField(max_length=100, blank=True, help_text="Requested new value.")
    reason = models.TextField(help_text="Why this change is needed.")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="workflow_decisions"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.CharField(max_length=255, blank=True)

    current_stage = models.PositiveSmallIntegerField(default=0, help_text="Index of the approval stage waiting for a decision.")
    break_glass = models.BooleanField(default=False, help_text="Decided by the System Administrator because no office holder exists.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_request_type_display()} #{self.pk} ({self.get_status_display()})"

    @property
    def subject(self):
        if self.grade_entry_id:
            return str(self.grade_entry)
        if self.invoice_id:
            return str(self.invoice)
        return "-"


class WorkflowApproval(models.Model):
    """One recorded decision at one stage of a WorkflowRequest."""
    request = models.ForeignKey(WorkflowRequest, on_delete=models.CASCADE, related_name="approvals")
    stage = models.PositiveSmallIntegerField()
    stage_label = models.CharField(max_length=80)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decision = models.CharField(max_length=10, choices=[("approved", "Approved"), ("rejected", "Rejected")])
    notes = models.CharField(max_length=255, blank=True)
    break_glass = models.BooleanField(default=False)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["request_id", "stage", "decided_at"]
