from django import forms
from .models import Application, EntryTest


MAX_PREFERENCES = 5


class PreferenceFieldsMixin:
    """Adds up to 5 ranked program choices to an application form. Choice 1 is
    the only required one (it is the 'category' the application is filed and
    the application fee is charged under); the other four are optional. Each
    program may appear once, and choices must be filled in order."""

    def _add_preference_fields(self):
        from academics.models import Program
        qs = Program.objects.select_related('department').order_by('name')
        for n in range(1, MAX_PREFERENCES + 1):
            self.fields[f'preference_{n}'] = forms.ModelChoiceField(
                queryset=qs, required=(n == 1), empty_label='- none -',
                label=f'Program choice {n}' + (' (required)' if n == 1 else ' (optional)'),
                help_text='Your first choice decides the application fee.' if n == 1 else '')
        # put the preference fields first, in order
        order = [f'preference_{n}' for n in range(1, MAX_PREFERENCES + 1)]
        self.order_fields(order)

    def clean_preferences(self, cleaned):
        chosen, gap_at = [], None
        for n in range(1, MAX_PREFERENCES + 1):
            program = cleaned.get(f'preference_{n}')
            if program is None:
                gap_at = gap_at or n
                continue
            if gap_at:
                raise forms.ValidationError(f'Choice {n} is filled in but choice {gap_at} is empty - fill the choices in order.')
            if program.pk in [p.pk for p in chosen]:
                raise forms.ValidationError(f'{program.name} is selected more than once - each program can only appear once.')
            chosen.append(program)
        cleaned['ordered_programs'] = chosen
        return cleaned

    def save_with_preferences(self, applicant=None):
        """Save the application and its ranked ProgramPreference rows."""
        from .models import ProgramPreference
        programs = self.cleaned_data['ordered_programs']
        app = super().save(commit=False)
        app.program = programs[0]          # = allocated/first-choice program; updated when a seat is allocated
        if applicant is not None:
            app.applicant = applicant
        app.save()
        ProgramPreference.objects.bulk_create([ProgramPreference(application=app, program=p, rank=i) for i, p in enumerate(programs, start=1)])
        return app


class ApplicationForm(PreferenceFieldsMixin, forms.ModelForm):
    """Used by logged-in users applying from inside the dashboard."""
    class Meta:
        model = Application
        fields = ['previous_percentage', 'district', 'province', 'cnic_copy', 'education_certificate', 'domicile_certificate']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_preference_fields()
        self.fields['cnic_copy'].required = True
        self.fields['education_certificate'].required = True

    def clean(self):
        return self.clean_preferences(super().clean())


class PublicApplicationForm(PreferenceFieldsMixin, forms.ModelForm):
    """Used on the public /admissions/apply-now/ page - no login required."""
    class Meta:
        model = Application
        fields = ['full_name', 'cnic', 'email', 'phone', 'previous_percentage', 'district', 'province', 'cnic_copy', 'education_certificate', 'domicile_certificate']
        widgets = {
            'full_name': forms.TextInput(attrs={'placeholder': 'Full name'}),
            'cnic': forms.TextInput(attrs={'placeholder': '12345-1234567-1'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
            'phone': forms.TextInput(attrs={'placeholder': '+92 300 1234567'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_preference_fields()
        self.fields['full_name'].required = True
        self.fields['cnic'].required = True
        self.fields['cnic_copy'].required = True
        self.fields['education_certificate'].required = True

    def clean(self):
        cleaned = self.clean_preferences(super().clean())
        if not cleaned.get('email') and not cleaned.get('phone'):
            raise forms.ValidationError('Please provide at least an email or phone number so we can contact you.')
        return cleaned


class EntryTestScheduleForm(forms.ModelForm):
    class Meta:
        model = EntryTest
        fields = ['test_date', 'test_time', 'venue']
        widgets = {
            'test_date': forms.DateInput(attrs={'type': 'date'}),
            'test_time': forms.TimeInput(attrs={'type': 'time'}),
        }


class EntryTestResultForm(forms.ModelForm):
    class Meta:
        model = EntryTest
        fields = ['marks_obtained']
        help_texts = {'marks_obtained': f'Out of 100. Strictly greater than {EntryTest.PASS_MARK} to pass.'}


class PreferencesForm(forms.Form):
    """Up to 5 ranked program choices. Choice 1 is required; each program may
    appear only once; choices must be filled in order (no gap such as a 3rd
    choice with no 2nd) so the ranking is unambiguous."""

    def __init__(self, *args, programs=None, **kwargs):
        super().__init__(*args, **kwargs)
        from academics.models import Program
        qs = programs if programs is not None else Program.objects.all()
        for n in range(1, MAX_PREFERENCES + 1):
            self.fields[f'preference_{n}'] = forms.ModelChoiceField(
                queryset=qs, required=(n == 1), empty_label='- none -',
                label=f'Preference {n}' + (' (first choice)' if n == 1 else ''),
            )

    def clean(self):
        cleaned = super().clean()
        chosen = []
        gap_at = None
        for n in range(1, MAX_PREFERENCES + 1):
            program = cleaned.get(f'preference_{n}')
            if program is None:
                gap_at = gap_at or n
                continue
            if gap_at:
                raise forms.ValidationError(f'Preference {n} is filled in but preference {gap_at} is empty - fill the choices in order.')
            if program.pk in [p.pk for p in chosen]:
                raise forms.ValidationError(f'{program.name} is selected more than once - each program can only appear once.')
            chosen.append(program)
        cleaned['ordered_programs'] = chosen
        return cleaned
