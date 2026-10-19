from django import forms
from django.contrib.auth.models import User
from django.utils import timezone

from .constants import SCOPE_CHOICES
from .models import PolicyRule, Role, RoleAssignment
from .permissions import user_sod_conflicts, sod_conflicts


def _check_scope(form, data):
    if data.get('scope_type') and data['scope_type'] != 'university' and not data.get('scope_id'):
        form.add_error('scope_id', 'Required when the scope is not the whole university.')


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ['name', 'code', 'description', 'is_active']


class SubAdminCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=100, required=False)
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    role = forms.ModelChoiceField(queryset=Role.objects.filter(is_active=True))
    scope_type = forms.ChoiceField(choices=SCOPE_CHOICES, initial='university')
    scope_id = forms.IntegerField(required=False, help_text='ID of the faculty/department/program when not university-wide.')
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}), help_text='Optional expiry (temporary access).')

    def clean_username(self):
        u = self.cleaned_data['username']
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('That username already exists.')
        return u

    def clean(self):
        data = super().clean()
        _check_scope(self, data)
        if data.get('end_date') and data['end_date'] < timezone.localdate():
            self.add_error('end_date', 'Expiry cannot be in the past.')
        if data.get('role'):
            for label in sod_conflicts(data['role'].permission_pairs()):
                self.add_error('role', f'Separation of duties: {label}.')
        return data


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = RoleAssignment
        fields = ['user', 'role', 'scope_type', 'scope_id', 'start_date', 'end_date', 'reason']
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'}), 'end_date': forms.DateInput(attrs={'type': 'date'})}

    def clean(self):
        data = super().clean()
        _check_scope(self, data)
        s, e = data.get('start_date'), data.get('end_date')
        if s and e and e < s:
            self.add_error('end_date', 'End date must be after start date.')
        user, role = data.get('user'), data.get('role')
        if user and role:
            if user.is_superuser:
                self.add_error('user', 'The System Administrator is the system owner and cannot hold an office role; give office roles to a separate person.')
            else:
                for label in user_sod_conflicts(user, extra_role=role):
                    self.add_error('role', f'Separation of duties: {label}. Use a different person for this role.')
        return data


class PolicyVersionForm(forms.Form):
    rule = forms.ModelChoiceField(queryset=PolicyRule.objects.all())
    value = forms.CharField(max_length=255)
    scope_type = forms.ChoiceField(choices=SCOPE_CHOICES, initial='university')
    scope_id = forms.IntegerField(required=False)
    effective_from = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}), initial=timezone.localdate)
    effective_until = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    reason = forms.CharField(max_length=255, required=False)

    def clean(self):
        data = super().clean()
        rule = data.get('rule')
        if rule and data.get('value') not in (None, ''):
            try:
                rule.cast(data['value'])
            except (ValueError, ArithmeticError):
                self.add_error('value', f'Value must be a valid {rule.get_value_type_display().lower()}.')
        _check_scope(self, data)
        return data


class EmergencyAccessForm(forms.Form):
    DURATIONS = [(15, '15 minutes'), (30, '30 minutes'), (60, '60 minutes (maximum)')]
    reason = forms.CharField(min_length=20, max_length=300, widget=forms.Textarea(attrs={'rows': 3}),
                             help_text='Why is emergency access needed, and which office is vacant? At least 20 characters. This is audited.')
    minutes = forms.TypedChoiceField(choices=DURATIONS, coerce=int, initial=30)
