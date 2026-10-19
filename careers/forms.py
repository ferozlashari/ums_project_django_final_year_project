from django import forms
from .models import Employer, JobPosting, JobApplication, ResumeProfile


class EmployerForm(forms.ModelForm):
    class Meta:
        model = Employer
        fields = ['name', 'website', 'industry', 'description', 'contact_email']


class JobPostingForm(forms.ModelForm):
    class Meta:
        model = JobPosting
        fields = ['employer', 'title', 'posting_type', 'description', 'relevant_majors', 'location', 'application_deadline', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'application_deadline': forms.DateInput(attrs={'type': 'date'}),
        }


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['cover_note']
        widgets = {'cover_note': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Why are you a good fit for this role?'})}


class ResumeProfileForm(forms.ModelForm):
    class Meta:
        model = ResumeProfile
        fields = ['headline', 'summary', 'skills', 'experience', 'education_notes', 'links']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 3}),
            'experience': forms.Textarea(attrs={'rows': 4}),
            'education_notes': forms.Textarea(attrs={'rows': 2}),
        }
