"""Optional Celery tasks. These wrap the SAME AutomationService the
management command (core/management/commands/run_automation.py) and the
Automation Center UI button (core.views.automation_center) already call -
there is exactly one place the housekeeping logic lives, this is just a
third way to trigger it (on a schedule, via Celery Beat, instead of cron
or a manual click).

Not imported anywhere unless Celery is installed and a worker is running
- see ums_project/celery.py for how to actually run one.
"""
try:
    from celery import shared_task
except ImportError:
    shared_task = None

if shared_task:
    @shared_task
    def run_automation_task(dry_run=False):
        """Same call the 'Run Automation Now' button and `manage.py
        run_automation` make. Schedule this with Celery Beat (see
        CELERY_BEAT_SCHEDULE in settings.py) to run it periodically
        without any manual step."""
        from core.services.automation import AutomationService
        if dry_run:
            return AutomationService.run(dry_run=True, trigger='celery')
        from core import scheduler
        return scheduler.run_job('automation', trigger='celery', force=True)

    @shared_task
    def recalculate_risk_task():
        """Same call the Risk dashboard's 'Recalculate Now' button makes."""
        from risk_analytics.scoring import recalculate_risk_flags
        return recalculate_risk_flags()

    @shared_task
    def scheduler_tick_task():
        """Celery Beat entry point: one pass over the shared, DB-locked jobs.
        Same code path as `manage.py run_scheduler` and /internal/cron/."""
        from core import scheduler
        return [{'job': o['job'], 'status': o['status']}
                for o in scheduler.run_due_jobs(trigger='celery')]
