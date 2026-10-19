"""Built-in job scheduler - the free single-server alternative to Celery.

Why this exists
---------------
Celery needs Redis plus two extra processes (worker + beat). Free hosting
tiers usually give you ONE web process and nothing else. This module lets
the same recurring housekeeping run with no Redis and no extra service:

* ``python manage.py run_scheduler``      long-running loop (run it next to
                                          gunicorn, see deployment/start-single.sh)
* ``python manage.py run_scheduler --once``  one pass, for OS cron / systemd timers
* ``/internal/cron/`` (CRON_SECRET)       lets an external pinger (cron-job.org,
                                          UptimeRobot, GitHub Actions) trigger a
                                          pass - which also wakes a sleeping free host.

Safety
------
Every job is guarded by a database lock (``SchedulerJob.locked_until``), so
two processes - or this scheduler plus Celery Beat - can never run the same
job at once. Each job only runs when it is actually *due* (its interval has
elapsed since the last successful start), so calling a pass every minute, or
from three different triggers, still runs each job once per interval.
Every job here is idempotent anyway; the lock is belt and braces.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('ums.scheduler')

LOCK_TTL = timedelta(minutes=30)   # a crashed run frees its lock after this


def _job_automation(trigger):
    from core.models import log_action
    from core.services.automation import AutomationService
    stats = AutomationService.run(dry_run=False, trigger=trigger)
    # Same audit entry a button click or `manage.py run_automation` writes,
    # so the Automation Center's run history shows scheduled runs too.
    log_action(None, 'AUTOMATION_RUN', obj=f'live run (scheduled: {trigger})',
               changes={k: ['', str(v)] for k, v in stats.items()},
               reason='Triggered by the UMS scheduler, not the web UI.')
    return stats


def _job_risk(trigger):
    from risk_analytics.scoring import recalculate_risk_flags
    return recalculate_risk_flags()


def _job_data_quality(trigger):
    from core.services.data_quality import DataQualityService
    return {'issues_found': DataQualityService.scan()}


# name -> (callable, interval, human description)
JOBS = {
    'automation': (_job_automation, timedelta(hours=6),
                   'Fee reminders, late fees, challans, low-attendance and academic-standing housekeeping'),
    'risk_recalc': (_job_risk, timedelta(hours=24), 'Recalculate student risk flags'),
    'data_quality': (_job_data_quality, timedelta(hours=24), 'Scan for academic data-integrity problems'),
}


def scheduler_mode():
    """'celery' | 'builtin' | 'external' | 'off' - what the operator chose."""
    return getattr(settings, 'SCHEDULER_MODE', 'builtin')


def _acquire(name, now):
    """Atomically take the lock for `name`. True only for the winner."""
    from core.models import SchedulerJob
    SchedulerJob.objects.get_or_create(name=name)
    won = SchedulerJob.objects.filter(name=name).exclude(locked_until__gt=now).update(
        locked_until=now + LOCK_TTL)
    return bool(won)


def is_due(job, interval, now):
    return job.last_started is None or (now - job.last_started) >= interval


def run_job(name, trigger='manual', force=False, now=None):
    """Run one job if it is due (or `force`) and nobody else holds its lock.

    Returns a dict ``{'job', 'status', ...}`` where status is one of
    completed | failed | skipped. Never raises - a failing job is recorded
    (and surfaced in the Exception Center) so the scheduler loop survives.
    """
    from core.models import SchedulerJob, ExceptionRecord
    if name not in JOBS:
        raise KeyError(f'Unknown scheduled job: {name}')
    func, interval, _ = JOBS[name]
    now = now or timezone.now()

    row, _created = SchedulerJob.objects.get_or_create(name=name)
    if not force and not is_due(row, interval, now):
        return {'job': name, 'status': 'skipped', 'reason': 'not due yet'}
    if not _acquire(name, now):
        return {'job': name, 'status': 'skipped', 'reason': 'locked by another runner'}
    # Re-check under the lock: another runner may have started AND finished
    # between our first due-check and winning the lock; without this we
    # would run the job a second time right behind it.
    if not force:
        fresh = SchedulerJob.objects.get(name=name)
        if not is_due(fresh, interval, now):
            SchedulerJob.objects.filter(name=name).update(locked_until=None)
            return {'job': name, 'status': 'skipped', 'reason': 'ran meanwhile'}

    SchedulerJob.objects.filter(name=name).update(last_started=now, last_trigger=trigger)
    status, error, result = 'completed', '', {}
    try:
        result = func(trigger) or {}
    except Exception as exc:  # noqa: BLE001 - recorded, never propagated
        status, error = 'failed', f'{type(exc).__name__}: {exc}'
        logger.exception('Scheduled job %s failed', name)
        try:
            ExceptionRecord.objects.create(
                code='scheduler_job_failed', severity='warning', module='automation',
                message=f'Scheduled job "{name}" failed: {exc}',
                object_type='SchedulerJob', object_id=name, details={'trigger': trigger},
            )
        except Exception:  # noqa: BLE001
            logger.exception('Could not record ExceptionRecord for %s', name)
    finally:
        done = timezone.now()
        row = SchedulerJob.objects.get(name=name)
        row.last_finished, row.last_status, row.last_error = done, status, error
        row.last_result = _json_safe(result)
        row.run_count += 1
        if status == 'failed':
            row.failure_count += 1
            # Retry sooner than a full interval, but never in a hot loop.
            row.last_started = done - interval + timedelta(minutes=15)
        row.locked_until = None
        row.save()
    return {'job': name, 'status': status, 'result': result, 'error': error}


def _json_safe(value):
    try:
        import json
        json.dumps(value)
        return value
    except TypeError:
        return {k: str(v) for k, v in dict(value).items()} if isinstance(value, dict) else str(value)


def run_due_jobs(trigger='builtin', only=None, force=False):
    """One scheduler pass over every job. Returns the per-job outcomes."""
    return [run_job(n, trigger=trigger, force=force) for n in (only or JOBS)]


def job_overview(now=None):
    """Rows for the Automation Center: real state only, no invented times."""
    from core.models import SchedulerJob
    now = now or timezone.now()
    state = {j.name: j for j in SchedulerJob.objects.all()}
    rows = []
    for name, (_f, interval, description) in JOBS.items():
        j = state.get(name)
        due_at = (j.last_started + interval) if (j and j.last_started) else None
        rows.append({
            'name': name, 'description': description, 'interval': interval,
            'last_started': j.last_started if j else None,
            'last_finished': j.last_finished if j else None,
            'last_status': (j.last_status if j else '') or 'never run',
            'last_trigger': j.last_trigger if j else '',
            'last_error': j.last_error if j else '',
            'run_count': j.run_count if j else 0,
            'failure_count': j.failure_count if j else 0,
            'due': bool(due_at is None or due_at <= now),
            'next_due': due_at,
        })
    return rows
