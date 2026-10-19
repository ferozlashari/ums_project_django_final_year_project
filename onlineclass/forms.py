from django import forms
from .models import OnlineClass


class OnlineClassForm(forms.ModelForm):
    class Meta:
        model = OnlineClass
        fields = ['title', 'section', 'scheduled_at', 'duration_mins', 'notes']
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }
