from django import forms
from django.db import transaction
from core.forms_login import NewLoginFormMixin
from .models import Staff, Payroll


class StaffForm(NewLoginFormMixin, forms.ModelForm):
    password_required = True

    class Meta:
        model = Staff
        fields = ['user', 'employee_id', 'department', 'role', 'hire_date', 'monthly_salary']
        widgets = {
            'hire_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creating = self.instance.pk is None
        if self.creating:
            self._add_login_fields()
            self.order_fields(['user', 'new_username', 'new_password', 'new_first_name', 'new_last_name',
                               'new_email', 'employee_id', 'department', 'role', 'hire_date', 'monthly_salary'])

    def clean(self):
        cleaned = super().clean()
        if self.creating:
            self.clean_login(cleaned)
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        if self.creating:
            from core.services.accounts import profile_role_for_job
            self.login_role = profile_role_for_job(self.cleaned_data.get('role'))
            self.instance.user = self.create_login_if_needed()
        return super().save(commit)


class PayrollForm(forms.ModelForm):
    class Meta:
        model = Payroll
        fields = ['staff', 'month', 'amount']
        widgets = {'month': forms.DateInput(attrs={'type': 'date'})}


class PayrollPayForm(forms.ModelForm):
    class Meta:
        model = Payroll
        fields = ['reference']
