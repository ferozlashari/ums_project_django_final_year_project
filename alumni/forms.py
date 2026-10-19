from django import forms
from .models import AlumniProfile, MentorshipRequest


class AlumniProfileForm(forms.ModelForm):
    class Meta:
        model = AlumniProfile
        fields = [
            'graduation_year', 'current_employer', 'job_title', 'industry',
            'city', 'country', 'linkedin_url', 'bio', 'willing_to_mentor', 'is_public',
        ]
        widgets = {'bio': forms.Textarea(attrs={'rows': 4})}


class MentorshipRequestForm(forms.ModelForm):
    class Meta:
        model = MentorshipRequest
        fields = ['message']
        widgets = {'message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Introduce yourself and say what kind of guidance you\'re looking for.'})}
