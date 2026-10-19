from django.core.management.base import BaseCommand
from core.services.automation import AutomationService


class Command(BaseCommand):
    help = 'Run idempotent UMS housekeeping: due-fee reminders, overdue monitoring, and low-attendance warnings.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Calculate actions without creating notifications.')

    def handle(self, *args, **opts):
        stats = AutomationService.run(dry_run=opts['dry_run'])
        self.stdout.write(self.style.SUCCESS('Automation completed: ' + ', '.join(f'{k}={v}' for k, v in stats.items())))

        # Record this run in the same audit trail a web-triggered run uses,
        # so the Automation Center's "Last Run" reflects cron/systemd-timer
        # runs too, not only ones clicked through the browser. actor=None
        # is the documented way to log a system/automation-triggered event
        # (see core.models.log_action).
        from core.models import log_action
        log_action(
            None, 'AUTOMATION_RUN',
            obj='dry run (scheduled)' if opts['dry_run'] else 'live run (scheduled)',
            changes={k: ['', str(v)] for k, v in stats.items()},
            reason='Triggered via manage.py run_automation (cron/systemd timer, not the web UI).',
        )
