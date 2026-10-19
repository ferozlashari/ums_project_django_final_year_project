import signal
import time

from django.core.management.base import BaseCommand

from core import scheduler


class Command(BaseCommand):
    help = ('Built-in scheduler: runs the UMS recurring jobs (automation, risk, data quality) '
            'without Celery or Redis. Use --once from cron/systemd timers.')

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run one pass and exit.')
        parser.add_argument('--force', action='store_true', help='Run jobs even if not yet due.')
        parser.add_argument('--job', action='append', choices=sorted(scheduler.JOBS),
                            help='Only this job (repeatable).')
        parser.add_argument('--tick', type=int, default=60,
                            help='Seconds between passes in loop mode (default 60).')

    def handle(self, *args, **opts):
        only = opts['job']
        self._stop = False

        def _graceful(*_):
            self._stop = True
        signal.signal(signal.SIGTERM, _graceful)
        signal.signal(signal.SIGINT, _graceful)

        while True:
            for outcome in scheduler.run_due_jobs(trigger='builtin', only=only, force=opts['force']):
                if outcome['status'] == 'skipped':
                    continue
                style = self.style.SUCCESS if outcome['status'] == 'completed' else self.style.ERROR
                self.stdout.write(style(f"[{outcome['job']}] {outcome['status']} "
                                        f"{outcome.get('error') or outcome.get('result') or ''}"))
            opts['force'] = False   # --force applies to the first pass only
            if opts['once'] or self._stop:
                return
            # Sleep in 1s slices so SIGTERM stops us promptly.
            for _ in range(max(1, opts['tick'])):
                if self._stop:
                    return
                time.sleep(1)
