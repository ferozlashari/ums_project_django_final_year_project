"""Optional 'create the login at the same time' fields for the Teacher and Student forms."""
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password


class NewLoginFormMixin:
    """Adds username/password/name/email fields. When `user` is left empty the form creates the
    login itself; when `user` is chosen the new-login fields must stay empty.
    Subclasses set `login_role` (callable or str) and `password_required`."""
    password_required = True
    login_role = 'student'

    def _add_login_fields(self):
        self.fields['user'].required = False
        self.fields['user'].help_text = 'Pick an existing login - OR leave empty and fill "New login" below.'
        self.fields['new_username'] = forms.CharField(label='New login: username', max_length=150, required=False,
                                                      help_text='e.g. imran.shah - lower case, must be unique.')
        self.fields['new_password'] = forms.CharField(label='New login: password', required=False, min_length=8,
                                                      widget=forms.PasswordInput(render_value=False),
                                                      help_text='8+ characters.' + ('' if self.password_required else
                                                                ' Leave blank to create the account disabled (the person sets a password with "Forgot password").'))
        self.fields['new_first_name'] = forms.CharField(label='New login: first name', max_length=150, required=False)
        self.fields['new_last_name'] = forms.CharField(label='New login: last name', max_length=150, required=False)
        self.fields['new_email'] = forms.EmailField(label='New login: email', required=False)

    def clean_login(self, cleaned):
        user = cleaned.get('user')
        username = (cleaned.get('new_username') or '').strip()
        if user and (username or cleaned.get('new_password')):
            raise forms.ValidationError('Choose an existing login OR create a new one - not both.')
        if not user and not username:
            raise forms.ValidationError('Pick an existing login, or fill in "New login: username" to create one.')
        if not user:
            if User.objects.filter(username__iexact=username).exists():
                self.add_error('new_username', 'That username already exists - pick it in "User" instead.')
            pw = cleaned.get('new_password') or ''
            if self.password_required and not pw:
                self.add_error('new_password', 'A password is required for a new login.')
            elif pw:
                try:
                    validate_password(pw, User(username=username))
                except forms.ValidationError as exc:
                    self.add_error('new_password', exc)
        return cleaned

    def create_login_if_needed(self):
        if self.cleaned_data.get('user'):
            return self.cleaned_data['user']
        from core.services.accounts import create_login
        role = self.login_role() if callable(self.login_role) else self.login_role
        return create_login(self.cleaned_data['new_username'], self.cleaned_data.get('new_password') or '',
                            self.cleaned_data.get('new_first_name', ''), self.cleaned_data.get('new_last_name', ''),
                            self.cleaned_data.get('new_email', ''), role=role)
