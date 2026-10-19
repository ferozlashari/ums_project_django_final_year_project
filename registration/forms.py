from django import forms
from django.db import transaction
from core.forms_login import NewLoginFormMixin
from .models import Student


class StudentForm(NewLoginFormMixin, forms.ModelForm):
    password_required = False   # students may be created disabled and set a password via 'Forgot password'
    login_role = 'student'

    class Meta:
        model = Student
        fields = '__all__'
        widgets = {
            'cnic': forms.TextInput(attrs={'placeholder': '12345-1234567-1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.creating = self.instance.pk is None
        if self.creating:
            self._add_login_fields()
            self.order_fields(['user', 'new_username', 'new_password', 'new_first_name', 'new_last_name', 'new_email'])
        # CNIC is compulsory for new/edited student records (kept optional at
        # the database level only so this doesn't break pre-existing rows).
        self.fields['cnic'].required = True

    def clean_cnic(self):
        from core.encrypted_fields import is_decryption_unavailable
        value = self.cleaned_data.get('cnic')
        if is_decryption_unavailable(value):
            # The stored CNIC couldn't be decrypted (see EncryptedCharField) -
            # its form field was pre-filled with a placeholder, not the real
            # value. Never let that placeholder text get saved as if it were
            # a real CNIC - make the person re-enter the correct number.
            raise forms.ValidationError(
                "This student's CNIC couldn't be loaded correctly and needs to be re-entered."
            )
        return value

    def clean(self):
        cleaned = super().clean()
        if self.creating:
            self.clean_login(cleaned)
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        if self.creating:
            self.instance.user = self.create_login_if_needed()
        return super().save(commit)
