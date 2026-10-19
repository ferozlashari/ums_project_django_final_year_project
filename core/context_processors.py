from datetime import datetime


def year_processor(request):
    return {'year': datetime.now().year}


def branding_processor(request):
    """Makes site branding available in every template - pulled from the
    admin-editable SiteSettings row, so changes on the Settings page take
    effect everywhere immediately."""
    from .models import SiteSettings
    try:
        settings_obj = SiteSettings.load()
        return {
            'site_name': settings_obj.site_name,
            'site_full_name': settings_obj.site_full_name,
            'site_tagline': settings_obj.site_tagline,
            'currency_symbol': settings_obj.currency_symbol,
            'require_biometric_attendance': settings_obj.require_biometric_attendance,
            'enable_guardian_portal': settings_obj.enable_guardian_portal,
        }
    except Exception:
        # Table may not exist yet (e.g. mid-migration) - fall back safely.
        return {
            'site_name': 'UMS', 'site_full_name': 'University Management System',
            'site_tagline': '', 'currency_symbol': 'Rs.', 'require_biometric_attendance': False,
            'enable_guardian_portal': False,
        }


def role_processor(request):
    """Makes the current user's role available in every template (for sidebar nav)."""
    from .permissions import user_role
    return {'current_role': user_role(request.user)}


def notifications_processor(request):
    """Makes the signed-in user's unread notification count and latest
    notifications available in every template, for the bell next to Logout."""
    if not request.user.is_authenticated:
        return {}
    try:
        from .models import Notification
        qs = Notification.objects.filter(user=request.user)
        return {
            'unread_notification_count': qs.filter(is_read=False).count(),
            'recent_notifications': qs[:8],
        }
    except Exception:
        return {}


def governance_nav_processor(request):
    """Sidebar flags for office roles. Only users who actually hold an office
    assignment (or are the Super Administrator) cost any extra queries."""
    user = request.user
    flags = {'nav_office_roles': False, 'nav_executive': False, 'nav_approvals': False, 'nav_matrix': False, 'nav_provision': False}
    if not user.is_authenticated:
        return flags
    try:
        from governance.models import RoleAssignment
        from governance.permissions import has_perm
        if user.is_superuser:
            flags.update(nav_matrix=True, nav_approvals=True, nav_executive=True)
            return flags
        if not RoleAssignment.objects.filter(user=user, is_active=True).exists():
            return flags
        flags['nav_office_roles'] = True
        flags['nav_executive'] = has_perm(user, 'executive', 'view')
        flags['nav_matrix'] = has_perm(user, 'security', 'view') or has_perm(user, 'audit', 'view')
        from governance.permissions import provisionable_role_codes
        flags['nav_provision'] = bool(provisionable_role_codes(user))
        flags['nav_approvals'] = any(has_perm(user, m, a) for m, a in (
            ('results', 'verify'), ('results', 'override'), ('finance', 'reconcile'),
            ('finance', 'approve'), ('registration', 'approve'), ('executive', 'approve')))
    except Exception:
        pass
    return flags
