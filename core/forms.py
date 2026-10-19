import re
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Notice, Profile, SiteSettings

USERNAME_RE = re.compile(r'^[A-Za-z]+$')
CNIC_RE = re.compile(r'^\d{5}-\d{7}-\d{1}$')


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    full_name = forms.CharField(max_length=150, required=True, label='Full Name')
    cnic = forms.CharField(
        max_length=15, required=True, label='CNIC / National ID',
        widget=forms.TextInput(attrs={'placeholder': '12345-1234567-1'}),
        help_text='Required for identity verification (format: 12345-1234567-1).',
    )
    # Required only when registering as a Student (validated in the view, since
    # the role choice lives outside this form's fields). A student without a
    # program would see no courses.
    program = forms.ModelChoiceField(
        queryset=None, required=False, label='Degree / Program',
        help_text='Required if registering as a Student.',
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from academics.models import Program
        self.fields['program'].queryset = Program.objects.select_related('department').order_by('name')

    def clean_username(self):
        username = self.cleaned_data['username']
        if not USERNAME_RE.match(username):
            raise forms.ValidationError('Username must contain letters only — no numbers or special characters.')
        if len(username) < 3:
            raise forms.ValidationError('Username must be at least 3 characters long.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists. Try logging in or resetting your password.')
        return email

    def clean_cnic(self):
        cnic = self.cleaned_data['cnic'].strip()
        if not CNIC_RE.match(cnic):
            raise forms.ValidationError('Enter CNIC in the format 12345-1234567-1 (13 digits with dashes).')
        from registration.models import Student
        if Student.objects.filter(cnic=cnic).exists():
            raise forms.ValidationError('An account is already registered with this CNIC.')
        return cnic


class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = ['title', 'body']


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    # Lives on registration.Student, not core.Profile - included here so
    # students have exactly one "Edit Profile" page to fill in everything
    # about themselves, rather than a field that's referenced elsewhere
    # (hostel eligibility) but has no form anywhere that can set it.
    gender = forms.ChoiceField(
        choices=[('', '— Select —')],  # populated in __init__ from Student.GENDER_CHOICES
        required=False,
        help_text='Used to match gender-specific hostel availability. Only visible to you and staff.',
    )
    # Only ever shown/settable when the student's program is currently
    # blank (see edit_profile view) - a one-time self-service fix for
    # accounts created through the direct signup form before it collected
    # a program, or any other path that left this unset. Not editable
    # once set, since changing programs afterward should go through an
    # administrator (it affects eligibility, fees, and past records).
    program = forms.ModelChoiceField(queryset=None, required=False, label='Degree / Program')
    district = forms.CharField(max_length=100, required=False, help_text='Your domicile district.')
    province = forms.ChoiceField(choices=[('', '— Select —')], required=False)

    class Meta:
        model = Profile
        fields = ['photo', 'phone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from registration.models import Student, PROVINCE_CHOICES
        from academics.models import Program
        self.fields['gender'].choices = [('', '— Select —')] + list(Student.GENDER_CHOICES)
        self.fields['program'].queryset = Program.objects.select_related('department').order_by('name')
        self.fields['province'].choices = [('', '— Select —')] + list(PROVINCE_CHOICES)

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        return email


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'notify_email_notices', 'notify_email_fees', 'notify_email_complaints',
            'biometric_attendance_enabled',
            'high_contrast_mode', 'text_only_mode', 'sms_fallback_number',
        ]


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            'site_name', 'site_full_name', 'site_tagline', 'contact_email', 'currency_symbol',
            'allow_public_registration', 'allow_public_admissions', 'enable_guardian_portal',
            'maintenance_mode', 'maintenance_message',
            'bank_name', 'bank_account_title', 'bank_account_no', 'bank_iban',
            'jazzcash_number', 'easypaisa_number', 'llm_provider',
            'require_biometric_attendance',
            'max_login_attempts', 'login_lockout_minutes', 'require_2fa_for_admin', 'session_timeout_minutes',
            'minimum_attendance_percent', 'max_registration_credits', 'max_retake_attempts', 'max_improvement_attempts', 'late_fee_percent',
            'hostel_annual_fee', 'retake_window_years', 'marks_lock_days',
            'retake_fee_amount', 'improvement_fee_amount',
        ]
