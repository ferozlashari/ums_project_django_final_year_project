from django import forms
from .models import AttendanceRecord


class AttendanceForm(forms.ModelForm):
    class Meta:
        model = AttendanceRecord
        fields = ['student', 'section', 'date', 'present', 'remarks']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }
