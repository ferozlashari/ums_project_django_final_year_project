from django import forms
from .models import WorkflowRequest


class WorkflowRequestForm(forms.ModelForm):
    class Meta:
        model = WorkflowRequest
        fields = ["request_type", "grade_entry", "invoice", "old_value", "new_value", "reason"]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, role=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from exams.models import GradeEntry
        from finance.models import Invoice
        from core.permissions import teaching_sections

        self.fields["grade_entry"].required = False
        self.fields["invoice"].required = False

        if role == "faculty":
            # Teachers may only request corrections for marks they
            # actually teach - never a colleague's class.
            sections = teaching_sections(user)
            self.fields["grade_entry"].queryset = GradeEntry.objects.filter(exam__course__sections__in=sections).distinct()
            self.fields["invoice"].queryset = Invoice.objects.none()
            self.fields["request_type"].choices = [("marks_correction", "Marks Correction")]
        elif role == "staff":
            self.fields["grade_entry"].queryset = GradeEntry.objects.all()
            self.fields["invoice"].queryset = Invoice.objects.all()
            self.fields["request_type"].choices = [
                c for c in WorkflowRequest.TYPE_CHOICES if c[0] != "marks_correction"
            ]
        # admin (or anything else) keeps every field/choice as-is
