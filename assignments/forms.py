from django import forms
from .models import Assignment, Submission


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ['section', 'title', 'description', 'due_date', 'max_marks']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'due_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ['text_answer', 'file']
        widgets = {'text_answer': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Type your answer, or attach a file below.'})}


class GradeSubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ['marks_obtained', 'feedback']
        widgets = {'feedback': forms.Textarea(attrs={'rows': 3})}
