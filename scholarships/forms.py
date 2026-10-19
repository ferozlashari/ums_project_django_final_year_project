from django import forms
from .models import Scholarship, ScholarshipApplication


class ScholarshipForm(forms.ModelForm):
    class Meta:
        model = Scholarship
        fields = ['name', 'description', 'amount', 'eligibility_criteria', 'application_deadline', 'active']
        widgets = {'application_deadline': forms.DateInput(attrs={'type': 'date'})}


class ScholarshipApplyForm(forms.ModelForm):
    class Meta:
        model = ScholarshipApplication
        fields = ['statement']
        widgets = {'statement': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Briefly explain why you qualify…'})}
