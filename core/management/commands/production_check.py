from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connection
from django.core.mail import get_connection
from governance.models import Role, PolicyRule


class Command(BaseCommand):
    help = 'Run UMS production-readiness checks without changing application data.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Fail if external production services are not configured.')

    def handle(self, *args, **options):
        strict = options['strict']
        checks = []
        errors = []
        warnings = []

        def ok(name, detail):
            checks.append((name, 'OK', detail))

        def warn(name, detail):
            checks.append((name, 'WARN', detail)); warnings.append(f'{name}: {detail}')

        def fail(name, detail):
            checks.append((name, 'FAIL', detail)); errors.append(f'{name}: {detail}')

        if settings.DEBUG:
            warn('DEBUG', 'DEBUG=1; use DEBUG=0 for a live deployment.')
        else:
            ok('DEBUG', 'DEBUG=0')
        if settings.SECRET_KEY and not settings.SECRET_KEY.startswith('django-insecure-'):
            ok('SECRET_KEY', 'Production-style secret configured.')
        else:
            fail('SECRET_KEY', 'Set a strong DJANGO_SECRET_KEY.')
        enc_key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
        if not enc_key:
            fail('FIELD_ENCRYPTION_KEY', 'Sensitive encrypted fields require a stable key '
                 '(python manage.py generate_encryption_key). It must be identical on web, worker and beat.')
        else:
            try:
                from cryptography.fernet import Fernet
                Fernet(enc_key.encode())
                ok('FIELD_ENCRYPTION_KEY', 'Valid Fernet key configured (must be identical on web/worker/beat).')
            except Exception:
                fail('FIELD_ENCRYPTION_KEY', 'Set but NOT a valid Fernet key (need 32 url-safe base64 bytes); '
                     'encrypted fields will fail. Regenerate with generate_encryption_key.')

        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            if connection.vendor == 'sqlite' and not settings.DEBUG:
                warn('DATABASE', 'SQLite in a DEBUG=0 deployment: use PostgreSQL for real data.')
            else:
                ok('DATABASE', connection.vendor)
        except Exception as exc:
            fail('DATABASE', str(exc)[:200])

        try:
            conn = get_connection(fail_silently=True)
            if getattr(settings, 'EMAIL_BACKEND', '').endswith('console.EmailBackend'):
                warn('EMAIL', 'Console backend: messages are not delivered to user inboxes.')
            elif getattr(settings, 'EMAIL_HOST', '') and getattr(settings, 'DEFAULT_FROM_EMAIL', ''):
                ok('EMAIL', f'SMTP configured via {settings.EMAIL_HOST}.')
            else:
                fail('EMAIL', 'Configure SMTP_HOST/SMTP_USER/SMTP_PASSWORD and DEFAULT_FROM_EMAIL.')
            conn.close()
        except Exception as exc:
            fail('EMAIL', str(exc)[:200])

        mode = getattr(settings, 'SCHEDULER_MODE', 'builtin')
        cron_secret = getattr(settings, 'CRON_SECRET', '')
        broker = getattr(settings, 'CELERY_BROKER_URL', '')
        if mode == 'celery':
            if not broker:
                fail('SCHEDULER', 'SCHEDULER_MODE=celery but CELERY_BROKER_URL is empty.')
            else:
                try:
                    import redis
                    redis.Redis.from_url(broker, socket_connect_timeout=3).ping()
                    ok('SCHEDULER', 'celery: Redis broker reachable. Worker + beat processes still need runtime verification.')
                except Exception as exc:
                    fail('SCHEDULER', f'celery: broker not reachable ({type(exc).__name__}).')
        elif mode == 'builtin':
            ok('SCHEDULER', 'builtin: run `manage.py run_scheduler` next to the web process '
               '(deployment/start-single.sh does this). Not running by itself in `runserver`/`gunicorn` alone.')
        elif mode == 'external':
            if len(cron_secret) >= 20:
                ok('SCHEDULER', 'external: /internal/cron/ enabled; an outside pinger must actually call it.')
            else:
                fail('SCHEDULER', 'external mode needs CRON_SECRET of at least 20 characters.')
        else:
            warn('SCHEDULER', 'off: no recurring jobs run; use the Automation Center button.')
        if cron_secret and len(cron_secret) < 20:
            warn('CRON_SECRET', 'Shorter than 20 characters, so /internal/cron/ stays disabled.')

        if getattr(settings, 'SAFEPAY_API_KEY', '') and getattr(settings, 'SAFEPAY_SECRET_KEY', ''):
            ok('SAFEPAY', 'Safepay credentials are present; perform a sandbox/live transaction test.')
        else:
            warn('SAFEPAY', 'Safepay credentials are not configured; online checkout is intentionally unavailable.')

        if not settings.DEBUG:
            if not getattr(settings, 'SESSION_COOKIE_SECURE', False):
                warn('HTTPS', 'SECURE_COOKIES is off: session cookies can travel over plain HTTP.')
            if not getattr(settings, 'SECURE_SSL_REDIRECT', False):
                warn('HTTPS', 'SECURE_SSL_REDIRECT is off (fine only if a proxy/platform already forces HTTPS).')

        try:
            role_count = Role.objects.filter(is_active=True).count()
            policy_count = PolicyRule.objects.count()
            ok('GOVERNANCE', f'{role_count} active roles, {policy_count} policy rules.')
        except Exception as exc:
            fail('GOVERNANCE', str(exc)[:200])

        for name, status, detail in checks:
            colour = self.style.SUCCESS if status == 'OK' else self.style.WARNING if status == 'WARN' else self.style.ERROR
            self.stdout.write(colour(f'[{status}] {name}: {detail}'))

        if strict and (errors or warnings):
            raise CommandError('Production checks did not pass in strict mode.')
        if errors:
            raise CommandError('Production readiness has blocking failures.')
