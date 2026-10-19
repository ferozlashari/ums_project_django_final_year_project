from rest_framework.permissions import BasePermission, SAFE_METHODS

from core.permissions import user_role


class IsAuthenticatedReadOnlyOrAdminWrite(BasePermission):
    """API-wide default: you must be logged in to read anything, and only
    admin/staff accounts may create, update, or delete through the API.
    Students and faculty get read-only access to shared academic data
    (faculties, departments, programs, courses, sections)."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return user_role(request.user) in ('admin', 'staff')
