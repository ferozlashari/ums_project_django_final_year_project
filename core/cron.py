"""Token-protected endpoint that lets an *external* pinger drive the scheduler.

Free hosting tiers put the whole app to sleep when idle, which also stops any
in-process loop. A free external pinger (cron-job.org, UptimeRobot, a GitHub
Actions schedule) calling this URL every 5-15 minutes both wakes the service
and runs whichever jobs are due. Disabled (404) unless CRON_SECRET is set.

    curl -X POST -H "Authorization: Bearer $CRON_SECRET" https://host/internal/cron/

The token may also be sent as ?token=... for pingers that cannot set headers;
header form is preferred because URLs end up in access logs.
"""
import hmac
import threading

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core import scheduler

MIN_SECRET_LENGTH = 20


def _supplied_token(request):
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return request.headers.get('X-Cron-Token') or request.GET.get('token', '')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def cron_tick(request):
    secret = getattr(settings, 'CRON_SECRET', '')
    if len(secret) < MIN_SECRET_LENGTH:
        raise Http404()           # feature off - behave as if the URL does not exist
    supplied = _supplied_token(request) or ''
    if not hmac.compare_digest(supplied.encode(), secret.encode()):
        return JsonResponse({'status': 'forbidden'}, status=403)

    if request.GET.get('wait') == '1':        # synchronous - tests, short jobs, debugging
        outcomes = scheduler.run_due_jobs(trigger='cron')
        return JsonResponse({'status': 'done', 'jobs': [
            {'job': o['job'], 'status': o['status']} for o in outcomes]})

    # Default: acknowledge immediately (free hosts cut requests at ~30s) and
    # run in the background. The DB lock stops overlapping passes.
    threading.Thread(target=scheduler.run_due_jobs, kwargs={'trigger': 'cron'}, daemon=True).start()
    return JsonResponse({'status': 'accepted'}, status=202)
