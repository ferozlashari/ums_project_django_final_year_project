"""Creating logins and keeping a person's profile role consistent."""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

# Staff job title -> profile role. Teaching posts are Faculty; office posts are Staff.
FACULTY_JOBS = {'dean', 'professor', 'associate_professor', 'assistant_professor', 'lecturer', 'teaching_assistant'}


def profile_role_for_job(job_title):
    return 'faculty' if job_title in FACULTY_JOBS else 'staff'


def create_login(username, password='', first_name='', last_name='', email='', role='student'):
    """Create a user and set the profile role. A blank password makes the account unusable until an
    administrator sets one or the person uses 'Forgot password' - no shared passwords are ever invented.
    'admin' is never assignable here: administrators are created deliberately in the Django admin."""
    if role == 'admin':
        raise ValueError('Administrator accounts are created in the Django admin, not here.')
    user = User(username=username.strip(), first_name=first_name.strip(), last_name=last_name.strip(),
                email=email.strip())
    if password:
        validate_password(password, user)
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()
    set_profile_role(user, role)
    return user


def set_profile_role(user, role):
    from core.models import Profile
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.role = role
    profile.save(update_fields=['role'])
    return profile
