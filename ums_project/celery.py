"""Celery application - entirely optional. The UMS works completely
without this; nothing imports or requires it unless you actually run a
Celery worker. Registration, fees, results, attendance - every core
workflow goes through Django views/services directly and does not depend
on a task queue existing.

What this DOES give you, if you choose to run it: the same housekeeping
AutomationService.run() already does (fee reminders, overdue detection,
low-attendance warnings, registration-deadline reminders) can run as a
scheduled background task instead of a manual button click or an
OS-level cron job - useful once you have Redis available to run it.

Requires (not installed by default - see requirements.txt):
    pip install celery redis

Run a worker:
    celery -A ums_project worker --loglevel=info

Run the scheduler (for the periodic task below):
    celery -A ums_project beat --loglevel=info

Both need CELERY_BROKER_URL pointing at a running Redis instance (see
.env.example) - this file only defines what WOULD run, it does not start
Redis or a worker process itself.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ums_project.settings')

app = Celery('ums_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
