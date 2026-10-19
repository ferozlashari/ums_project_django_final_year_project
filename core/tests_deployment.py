"""Deployment configuration: production_check honesty, platform host trust, health probes."""
import os
import subprocess
import unittest
import sys
from io import StringIO

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

GOOD_KEY = Fernet.generate_key().decode()


def _yaml():
    try:
        import yaml
        return yaml
    except ImportError:   # PyYAML is a dev-only dependency (requirements-dev.txt)
        raise unittest.SkipTest('PyYAML not installed')


def run_check(**kw):
    out = StringIO()
    try:
        call_command('production_check', stdout=out, **kw)
        return None, out.getvalue()
    except CommandError as exc:
        return exc, out.getvalue()


@override_settings(FIELD_ENCRYPTION_KEY=GOOD_KEY, SCHEDULER_MODE='builtin', EMAIL_HOST='smtp.example.com',
                   EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                   DEFAULT_FROM_EMAIL='UMS <no-reply@example.com>')
class ProductionCheckTests(TestCase):
    def test_valid_builtin_setup_has_no_blocking_failure(self):
        err, out = run_check()
        self.assertIsNone(err, out)
        self.assertIn('[OK] FIELD_ENCRYPTION_KEY', out)
        self.assertIn('[OK] SCHEDULER: builtin', out)

    @override_settings(FIELD_ENCRYPTION_KEY='not-a-fernet-key')
    def test_invalid_fernet_key_is_a_blocking_failure(self):
        err, out = run_check()
        self.assertIsNotNone(err)
        self.assertIn('NOT a valid Fernet key', out)

    @override_settings(FIELD_ENCRYPTION_KEY='')
    def test_missing_encryption_key_is_a_blocking_failure(self):
        self.assertIsNotNone(run_check()[0])

    @override_settings(SCHEDULER_MODE='celery', CELERY_BROKER_URL='')
    def test_celery_mode_without_broker_fails(self):
        err, out = run_check()
        self.assertIsNotNone(err)
        self.assertIn('CELERY_BROKER_URL is empty', out)

    @override_settings(SCHEDULER_MODE='celery', CELERY_BROKER_URL='redis://127.0.0.1:1/0')
    def test_celery_mode_with_unreachable_redis_fails_instead_of_claiming_ok(self):
        err, out = run_check()
        self.assertIsNotNone(err)
        self.assertIn('not reachable', out)

    @override_settings(SCHEDULER_MODE='external', CRON_SECRET='')
    def test_external_mode_requires_cron_secret(self):
        err, out = run_check()
        self.assertIsNotNone(err)
        self.assertIn('CRON_SECRET', out)

    @override_settings(SCHEDULER_MODE='external', CRON_SECRET='s' * 24)
    def test_external_mode_with_secret_passes(self):
        self.assertIsNone(run_check()[0])

    def test_strict_mode_fails_on_warnings(self):
        self.assertIsNotNone(run_check(strict=True)[0])   # DEBUG/console-email warnings


@override_settings(SECURE_SSL_REDIRECT=True)
class HealthProbeTests(TestCase):
    def test_probes_are_not_redirected_to_https(self):
        for url in ('/health/', '/ready/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_other_pages_still_redirect_to_https(self):
        self.assertEqual(self.client.get('/automation/').status_code, 301)


class SettingsEnvTests(TestCase):
    """Settings are read at import time, so exercise them in a fresh interpreter."""

    def _settings(self, expr, **env):
        e = {k: v for k, v in os.environ.items() if k not in
             ('CELERY_BROKER_URL', 'SCHEDULER_MODE', 'RENDER_EXTERNAL_HOSTNAME', 'RAILWAY_PUBLIC_DOMAIN')}
        e.update(DEBUG='1', **env)
        code = ("import os;os.environ['DJANGO_SETTINGS_MODULE']='ums_project.settings';"
                f"from django.conf import settings as s;print({expr})")
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=e,
                           cwd=str(settings.BASE_DIR))
        return r

    def test_no_broker_means_builtin_mode_and_no_phantom_redis(self):
        r = self._settings("(s.SCHEDULER_MODE, repr(s.CELERY_BROKER_URL))")
        self.assertIn("('builtin', \"''\")", r.stdout, r.stderr)

    def test_blank_scheduler_mode_from_env_example_means_auto(self):
        r = self._settings("s.SCHEDULER_MODE", SCHEDULER_MODE='')
        self.assertEqual(r.stdout.strip(), 'builtin', r.stderr)
        r = self._settings("s.SCHEDULER_MODE", SCHEDULER_MODE='', CELERY_BROKER_URL='redis://h:6379/0')
        self.assertEqual(r.stdout.strip(), 'celery', r.stderr)

    def test_env_example_loads_cleanly(self):
        env = {}
        for line in (settings.BASE_DIR / '.env.example').read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
        r = self._settings("(s.SCHEDULER_MODE, s.CRON_SECRET)", **{k: v for k, v in env.items() if k not in ('TIME_ZONE', 'DEBUG')})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_broker_set_means_celery_mode(self):
        r = self._settings("s.SCHEDULER_MODE", CELERY_BROKER_URL='redis://h:6379/0')
        self.assertEqual(r.stdout.strip(), 'celery', r.stderr)

    def test_invalid_scheduler_mode_refuses_to_start(self):
        r = self._settings("s.SCHEDULER_MODE", SCHEDULER_MODE='sometimes')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('SCHEDULER_MODE must be one of', r.stderr)

    def test_render_and_railway_hostnames_are_trusted_automatically(self):
        r = self._settings("(s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS)",
                           RENDER_EXTERNAL_HOSTNAME='ums-web.onrender.com',
                           RAILWAY_PUBLIC_DOMAIN='ums.up.railway.app')
        for needle in ('ums-web.onrender.com', 'https://ums-web.onrender.com',
                       'ums.up.railway.app', 'https://ums.up.railway.app'):
            self.assertIn(needle, r.stdout, r.stderr)

    def test_no_platform_vars_adds_nothing(self):
        r = self._settings("s.CSRF_TRUSTED_ORIGINS")
        self.assertEqual(r.stdout.strip(), '[]', r.stderr)


class DeploymentFilesTests(TestCase):
    """The shipped host configs must parse and must not reintroduce known mistakes."""
    root = settings.BASE_DIR

    def read(self, rel):
        return (self.root / rel).read_text()

    def test_yaml_and_toml_parse(self):
        import tomllib
        yaml = _yaml()
        for f in ('render.yaml', 'render-free.yaml', 'docker-compose.yml', 'docker-compose.lite.yml'):
            self.assertIsInstance(yaml.safe_load(self.read(f)), dict, f)
        tomllib.loads(self.read('railway.toml'))

    def test_render_blueprint_has_no_duplicated_env_keys_and_shares_secrets(self):
        yaml = _yaml()
        doc = yaml.safe_load(self.read('render.yaml'))
        for svc in doc['services']:
            keys = [e.get('key') for e in svc.get('envVars', []) if 'key' in e]
            self.assertEqual(len(keys), len(set(keys)), f"duplicate env keys in {svc['name']}")
        group_keys = {e['key'] for g in doc['envVarGroups'] for e in g['envVars']}
        self.assertTrue({'DJANGO_SECRET_KEY', 'FIELD_ENCRYPTION_KEY'} <= group_keys)
        for svc in doc['services']:
            if svc['type'] in ('web', 'worker'):
                self.assertIn({'fromGroup': 'ums-shared'}, svc['envVars'], svc['name'])
                self.assertNotEqual(svc.get('plan'), 'free', 'Render has no free worker plan')

    def test_free_blueprint_needs_no_redis_or_worker(self):
        yaml = _yaml()
        doc = yaml.safe_load(self.read('render-free.yaml'))
        self.assertEqual([s['type'] for s in doc['services']], ['web'])

    def test_only_web_container_runs_migrations(self):
        yaml = _yaml()
        svcs = yaml.safe_load(self.read('docker-compose.yml'))['services']
        for name in ('worker', 'beat'):
            self.assertEqual(svcs[name]['environment']['RUN_MIGRATIONS'], '0')
        self.assertIn('healthcheck', svcs['web'])

    def test_nginx_never_serves_media_publicly(self):
        for f in ('deployment/nginx.conf', 'deployment/nginx-vps.conf'):
            txt = self.read(f)
            self.assertNotIn('location /media/', txt, f)
            self.assertIn('internal;', txt, f)

    def test_systemd_units_share_one_env_file(self):
        for n in ('web', 'worker', 'beat', 'scheduler'):
            self.assertIn('EnvironmentFile=/etc/ums/ums.env', self.read(f'deployment/systemd/ums-{n}.service'))
