"""Applies SiteSettings.session_timeout_minutes to every authenticated
request's session, so the "auto-logout after inactivity" control in Site
Settings actually does something rather than sitting in the database
unused. Kept as a tiny, single-purpose middleware rather than baking this
into settings.py, since Django's SESSION_COOKIE_AGE is fixed at process
start and can't read from the database per-request.
"""
import logging

from django.contrib import messages
from django.http import JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import redirect, render

logger = logging.getLogger('ums.errors')


class DynamicSessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                from core.models import SiteSettings
                minutes = SiteSettings.load().session_timeout_minutes
                request.session.set_expiry(minutes * 60)
            except Exception:
                pass  # never let a settings lookup failure break the request
        return self.get_response(request)


class GlobalExceptionMiddleware:
    """Last line of defense: catches ANY exception a view raised that no
    other code handled, so a single bug in one page can never take down
    the whole app or dump a raw Python traceback in front of a user.

    Behaviour:
      - Always logs the full traceback (with the URL, method, and user)
        to the 'ums.errors' logger, so nothing is ever silently lost -
        check the console or logs/errors.log to see what actually broke.
      - In DEBUG mode, re-raises so Django's normal debug page still
        shows you the traceback while developing (set
        SHOW_TRACEBACK=1 in .env only when you explicitly want the developer traceback
        even locally, e.g. to test what end users will see).
      - Outside DEBUG (production), or when HIDE_TRACEBACK_IN_DEBUG=1:
          * JSON/AJAX/API requests get a clean {"error": "..."} response
            instead of an HTML crash page.
          * Normal page requests get redirected back with a friendly
            "something went wrong" message, or fall back to rendering
            500.html if there's nowhere sensible to redirect to.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        import os
        from django.conf import settings as dj_settings
        from django.core.exceptions import PermissionDenied
        from django.http import Http404

        # Expected HTTP-status exceptions (403/404) must reach Django's own
        # handler untouched, so role_required()/admin_required() etc. show
        # a real 403 page - not get mistaken for a crash and turned into a
        # vague "something went wrong" redirect that hides *why* access was
        # denied. Only genuinely unexpected exceptions fall through below.
        if isinstance(exception, (PermissionDenied, Http404)):
            return None

        logger.error(
            "Unhandled exception on %s %s (user=%s): %s",
            request.method,
            request.path,
            getattr(request.user, 'username', 'anonymous'),
            exception,
            exc_info=True,
        )

        show_traceback = dj_settings.DEBUG and os.environ.get('SHOW_TRACEBACK', '0') == '1'
        if show_traceback:
            return None  # let Django's normal debug page handle it

        wants_json = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or request.path.startswith('/api/')
            or 'application/json' in request.headers.get('accept', '')
        )
        if wants_json:
            return JsonResponse(
                {'error': 'An unexpected error occurred. Please try again.'},
                status=500,
            )

        referer = request.META.get('HTTP_REFERER')
        if referer and referer != request.build_absolute_uri() and url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            messages.error(request, "Something went wrong on our end - please try again.")
            return redirect(referer)

        try:
            messages.error(request, "Something went wrong on our end - please try again.")
            return redirect('dashboard')
        except Exception:
            return render(request, '500.html', status=500)
