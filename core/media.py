"""Authenticated media gateway.

Uploaded files include CNIC scans, medical certificates, guardian consent
letters, education certificates and student submissions. They must never be
fetchable by guessing a URL, so ``/media/<path>`` is NOT a public static
mount: every request goes through ``protected_media`` which

  1. requires a signed-in user,
  2. maps the file back to the database record that owns it and applies that
     record's access rule (owner / the staff who legitimately review it /
     System Admin), and denies anything it cannot map (deny by default),
  3. serves images and PDFs inline and everything else as a download, so an
     uploaded .html/.svg can never run script on the site's origin.

It also makes uploads work on gunicorn-only hosts (Render/Railway), where a
DEBUG-only static mount would 404 every file. Behind nginx set
MEDIA_ACCEL_PREFIX (see deployment/nginx.conf) so nginx streams the bytes
after Django has authorised the request.
"""
import mimetypes
import posixpath

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.core.exceptions import PermissionDenied

from core.permissions import user_role

INLINE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'}


def _staff_may_review(user, module):
    """Office staff / governance sub-admins who legitimately review a module's
    documents. Faculty and students never qualify. Governance assignments
    are always honoured; a bare is_staff flag is not a wildcard."""
    role = user_role(user)
    if role == 'admin':
        return True
    from governance.permissions import _current_assignments, has_perm
    if _current_assignments(user):
        return has_perm(user, module, 'view')
    return role == 'staff'


def _admission_doc(user, name):
    from admissions.models import Application
    apps = Application.objects.filter(
        Q(cnic_copy=name) | Q(education_certificate=name) | Q(domicile_certificate=name))
    if not apps.exists():
        return False
    return apps.filter(applicant=user).exists() or _staff_may_review(user, 'admissions')


def _hostel_doc(user, name):
    from hostel.models import HostelApplication
    apps = HostelApplication.objects.filter(
        Q(cnic_copy=name) | Q(guardian_consent_letter=name) | Q(medical_certificate=name))
    if not apps.exists():
        return False
    return apps.filter(student__user=user).exists() or _staff_may_review(user, 'hostel')


def _submission_file(user, name):
    from assignments.models import Submission
    subs = Submission.objects.filter(file=name)
    if not subs.exists():
        return False
    if subs.filter(student__user=user).exists():
        return True
    try:
        return subs.filter(assignment__section__instructor=user.staff_profile).exists()
    except Exception:
        return False


def _any_signed_in(user, name):
    return True


# prefix -> rule. Anything not listed is administrators-only.
RULES = (
    ('admission_docs/', _admission_doc),
    ('hostel_docs/', _hostel_doc),
    ('assignment_submissions/', _submission_file),
    ('profiles/', _any_signed_in),        # profile photos are shown across the portal
    ('library_books/', _any_signed_in),   # the library is open to every signed-in member
)


def can_access(user, name):
    if user_role(user) == 'admin':
        return True
    for prefix, rule in RULES:
        if name.startswith(prefix):
            return bool(rule(user, name))
    return False


def _normalise(path):
    name = posixpath.normpath(path.replace('\\', '/')).lstrip('/')
    if name.startswith('..') or name in ('', '.') or '\x00' in name:
        raise Http404()
    return name


@login_required
def protected_media(request, path):
    name = _normalise(path)
    if not can_access(request.user, name):
        raise PermissionDenied('You do not have access to this file.')
    try:
        if not default_storage.exists(name):
            raise Http404()
    except SuspiciousFileOperation:
        raise Http404()

    ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    inline = ctype in INLINE_TYPES
    filename = posixpath.basename(name)
    disposition = f'{"inline" if inline else "attachment"}; filename="{filename}"'

    accel = getattr(settings, 'MEDIA_ACCEL_PREFIX', '')
    if accel:
        resp = HttpResponse(content_type=ctype)
        resp['X-Accel-Redirect'] = accel.rstrip('/') + '/' + name
    else:
        resp = FileResponse(default_storage.open(name, 'rb'), content_type=ctype)
    resp['Content-Disposition'] = disposition
    resp['Cache-Control'] = 'private, no-store'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
