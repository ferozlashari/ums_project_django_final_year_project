from django import forms
from .models import GuardianLink


class GuardianLinkRequestForm(forms.ModelForm):
    admission_no = forms.CharField(
        max_length=120, label='Student admission number',
        help_text='Ask your child / ward for their admission number.',
    )

    class Meta:
        model = GuardianLink
        fields = ['relation']

    def clean_admission_no(self):
        from registration.models import Student
        admission_no = self.cleaned_data['admission_no'].strip()
        if not Student.objects.filter(admission_no=admission_no).exists():
            raise forms.ValidationError('No student found with that admission number.')
        return admission_no
