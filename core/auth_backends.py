"""
Lets students sign in with either their username OR their CNIC/roll number -
mirroring how real university portals (e.g. University of Sindh's ePortal)
work: "Roll No / CNIC (without dashes) + Password".
"""
import re
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class CNICOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username:
            return None

        # Try the normal username first (covers staff/admin/teacher logins).
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user:
            return user

        # Fall back to CNIC / admission number lookup for students, matching
        # digits-only input the way the reference portal expects.
        cleaned = re.sub(r'[^A-Za-z0-9]', '', username)
        if not cleaned:
            return None

        from registration.models import Student
        # Exact match on CNIC (regardless of dash formatting) or admission number.
        student = None
        for s in Student.objects.exclude(cnic='').select_related('user'):
            if re.sub(r'[^A-Za-z0-9]', '', s.cnic).lower() == cleaned.lower():
                student = s
                break
        if not student:
            student = Student.objects.filter(admission_no__iexact=username).select_related('user').first()

        if student and student.user and student.user.check_password(password):
            return student.user
        return None
