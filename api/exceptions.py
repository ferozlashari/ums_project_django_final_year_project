"""Custom DRF exception handler.

By default, DRF's exception handler only formats exceptions it knows about
(ValidationError, PermissionDenied, Http404, etc.) - anything else (a plain
Python bug: NameError, AttributeError, KeyError...) falls through and Django
renders its normal HTML error page, even for a JSON API endpoint. That's
confusing for API clients (they get HTML back where they expected JSON) and,
in DEBUG mode, leaks a full traceback to whoever's calling the API.

This wraps DRF's default handler: known DRF/API errors are still formatted
the normal DRF way, but any *other* exception is caught, logged, and turned
into a clean, generic JSON error response instead of propagating.
"""
import logging

from rest_framework.views import exception_handler as drf_default_exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger('ums.errors')


def ums_api_exception_handler(exc, context):
    response = drf_default_exception_handler(exc, context)
    if response is not None:
        # DRF already knows how to format this one (ValidationError, 404,
        # PermissionDenied, throttling, auth failures, etc.) - use as-is.
        return response

    # Anything else is an unexpected bug: log it with full context so it's
    # debuggable, but never let it leak a raw traceback to an API client.
    request = context.get('request')
    view = context.get('view')
    logger.error(
        "Unhandled exception in API view %s on %s: %s",
        getattr(view, '__class__', type(view)).__name__ if view else 'unknown',
        getattr(request, 'path', 'unknown'),
        exc,
        exc_info=True,
    )
    return Response(
        {'error': 'An unexpected error occurred. Please try again.'},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
