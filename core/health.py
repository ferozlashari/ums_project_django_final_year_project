"""Lightweight health/readiness endpoints for deployment monitoring.

These endpoints intentionally expose only operational status.  They never
return exception text, database credentials, settings, or application data.
"""
import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger("ums.errors")


@require_GET
def health(request):
    """Liveness probe: the Django process is responding."""
    return JsonResponse({"status": "ok", "service": "ums"})


@require_GET
def readiness(request):
    """Readiness probe: verify the configured database is reachable."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("UMS readiness check failed")
        return JsonResponse(
            {"status": "unavailable", "service": "ums"},
            status=503,
        )

    return JsonResponse({"status": "ready", "service": "ums"})
