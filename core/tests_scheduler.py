"""Built-in scheduler: DB locking, due-ness, failure isolation, cron endpoint."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import scheduler
from core.models import AutomationRun, ExceptionRecord, SchedulerJob

SECRET = 'x' * 32


class RunJobTests(TestCase):
    def test_first_run_executes_and_records_state(self):
        out = scheduler.run_job('data_quality', trigger='builtin')
        self.assertEqual(out['status'], 'completed')
        row = SchedulerJob.objects.get(name='data_quality')
        self.assertEqual(row.last_status, 'completed')
        self.assertEqual(row.last_trigger, 'builtin')
        self.assertEqual(row.run_count, 1)
        self.assertIsNone(row.locked_until, 'lock must be released after the run')

    def test_automation_job_records_trigger_on_the_run_history(self):
        scheduler.run_job('automation', trigger='cron')
        self.assertTrue(AutomationRun.objects.filter(trigger='cron', status__in=['completed', 'partial']).exists())

    def test_not_due_job_is_skipped(self):
        scheduler.run_job('data_quality')
        again = scheduler.run_job('data_quality')
        self.assertEqual(again['status'], 'skipped')
        self.assertEqual(SchedulerJob.objects.get(name='data_quality').run_count, 1)

    def test_force_overrides_due_check(self):
        scheduler.run_job('data_quality')
        self.assertEqual(scheduler.run_job('data_quality', force=True)['status'], 'completed')
        self.assertEqual(SchedulerJob.objects.get(name='data_quality').run_count, 2)

    def test_due_again_after_interval(self):
        scheduler.run_job('data_quality')
        SchedulerJob.objects.filter(name='data_quality').update(
            last_started=timezone.now() - timedelta(hours=25))
        self.assertEqual(scheduler.run_job('data_quality')['status'], 'completed')

    def test_held_lock_blocks_a_second_runner(self):
        SchedulerJob.objects.create(name='data_quality', locked_until=timezone.now() + timedelta(minutes=5))
        out = scheduler.run_job('data_quality', force=True)
        self.assertEqual(out['status'], 'skipped')
        self.assertIn('locked', out['reason'])
        self.assertEqual(SchedulerJob.objects.get(name='data_quality').run_count, 0)

    def test_runner_that_loses_the_race_after_another_finished_does_not_rerun(self):
        # B passes its due-check; A then runs and finishes; B wins the (now
        # free) lock. B must notice the job already ran and stand down.
        real_acquire = scheduler._acquire
        def acquire_after_other_runner_finished(name, now):
            SchedulerJob.objects.update_or_create(
                name=name, defaults={'last_started': now, 'last_status': 'completed', 'run_count': 1})
            return real_acquire(name, now)
        with mock.patch.object(scheduler, '_acquire', acquire_after_other_runner_finished):
            out = scheduler.run_job('data_quality')
        self.assertEqual(out['status'], 'skipped')
        row = SchedulerJob.objects.get(name='data_quality')
        self.assertEqual(row.run_count, 1, 'job must not run twice')
        self.assertIsNone(row.locked_until, 'lock must be released when standing down')

    def test_stale_lock_from_a_crashed_run_is_recoverable(self):
        SchedulerJob.objects.create(name='data_quality', locked_until=timezone.now() - timedelta(minutes=1))
        self.assertEqual(scheduler.run_job('data_quality')['status'], 'completed')

    def test_failing_job_is_recorded_not_raised_and_retries_soon(self):
        def boom(trigger):
            raise RuntimeError('kaput')
        jobs = dict(scheduler.JOBS)
        jobs['data_quality'] = (boom, timedelta(hours=24), 'x')
        with mock.patch.dict(scheduler.JOBS, jobs, clear=True):
            out = scheduler.run_job('data_quality')
            self.assertEqual(out['status'], 'failed')
            row = SchedulerJob.objects.get(name='data_quality')
            self.assertEqual(row.failure_count, 1)
            self.assertIn('kaput', row.last_error)
            self.assertIsNone(row.locked_until)
            self.assertTrue(ExceptionRecord.objects.filter(code='scheduler_job_failed').exists())
            # Not due immediately (no hot loop) ...
            self.assertEqual(scheduler.run_job('data_quality')['status'], 'skipped')
            # ... but due again well before a full 24h interval.
            later = timezone.now() + timedelta(minutes=20)
            self.assertEqual(scheduler.run_job('data_quality', now=later)['status'], 'failed')

    def test_one_failing_job_does_not_stop_the_others(self):
        def boom(trigger):
            raise RuntimeError('kaput')
        jobs = dict(scheduler.JOBS)
        jobs['automation'] = (boom, timedelta(hours=6), 'x')
        with mock.patch.dict(scheduler.JOBS, jobs, clear=True):
            statuses = {o['job']: o['status'] for o in scheduler.run_due_jobs()}
        self.assertEqual(statuses['automation'], 'failed')
        self.assertEqual(statuses['data_quality'], 'completed')
        self.assertEqual(statuses['risk_recalc'], 'completed')

    def test_unknown_job_name_raises(self):
        with self.assertRaises(KeyError):
            scheduler.run_job('nope')

    def test_overview_never_invents_run_times(self):
        rows = {r['name']: r for r in scheduler.job_overview()}
        self.assertEqual(rows['automation']['last_status'], 'never run')
        self.assertIsNone(rows['automation']['last_started'])
        self.assertTrue(rows['automation']['due'])


class RunSchedulerCommandTests(TestCase):
    def test_once_runs_every_due_job_then_exits(self):
        out = StringIO()
        call_command('run_scheduler', '--once', stdout=out)
        self.assertEqual(set(SchedulerJob.objects.values_list('name', flat=True)), set(scheduler.JOBS))
        self.assertIn('[automation] completed', out.getvalue())

    def test_job_filter(self):
        call_command('run_scheduler', '--once', '--job', 'data_quality', stdout=StringIO())
        self.assertEqual(list(SchedulerJob.objects.values_list('name', flat=True)), ['data_quality'])


@override_settings(CRON_SECRET=SECRET)
class CronEndpointTests(TestCase):
    url = '/internal/cron/'

    def test_rejects_missing_and_wrong_token(self):
        self.assertEqual(self.client.post(self.url + '?wait=1').status_code, 403)
        self.assertEqual(self.client.post(self.url + '?wait=1', HTTP_AUTHORIZATION='Bearer wrong').status_code, 403)
        self.assertEqual(SchedulerJob.objects.count(), 0)

    def test_bearer_token_runs_due_jobs(self):
        r = self.client.post(self.url + '?wait=1', HTTP_AUTHORIZATION=f'Bearer {SECRET}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual({j['job'] for j in r.json()['jobs']}, set(scheduler.JOBS))
        self.assertEqual(SchedulerJob.objects.get(name='automation').last_trigger, 'cron')

    def test_query_token_and_get_supported_for_simple_pingers(self):
        r = self.client.get(self.url, {'token': SECRET, 'wait': '1'})
        self.assertEqual(r.status_code, 200)

    def test_repeated_pings_do_not_rerun_jobs(self):
        for _ in range(3):
            self.client.post(self.url + '?wait=1', HTTP_AUTHORIZATION=f'Bearer {SECRET}')
        self.assertEqual(SchedulerJob.objects.get(name='automation').run_count, 1)

    def test_default_is_async_202(self):
        with mock.patch('core.cron.threading.Thread') as T:
            r = self.client.post(self.url, HTTP_AUTHORIZATION=f'Bearer {SECRET}')
        self.assertEqual(r.status_code, 202)
        T.return_value.start.assert_called_once()

    def test_works_without_csrf_token(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(self.url + '?wait=1', HTTP_AUTHORIZATION=f'Bearer {SECRET}').status_code, 200)

    def test_other_methods_not_allowed(self):
        self.assertEqual(self.client.delete(self.url, HTTP_AUTHORIZATION=f'Bearer {SECRET}').status_code, 405)


class CronDisabledTests(TestCase):
    @override_settings(CRON_SECRET='')
    def test_disabled_when_secret_unset(self):
        self.assertEqual(self.client.post('/internal/cron/', HTTP_AUTHORIZATION='Bearer anything').status_code, 404)

    @override_settings(CRON_SECRET='short')
    def test_short_secret_is_treated_as_disabled(self):
        self.assertEqual(self.client.post('/internal/cron/', HTTP_AUTHORIZATION='Bearer short').status_code, 404)


class AutomationCenterSchedulerPanelTests(TestCase):
    def test_center_shows_mode_and_real_job_state(self):
        admin = User.objects.create_superuser('sched_admin', 'a@x.com', 'pw')
        scheduler.run_job('data_quality', trigger='builtin')
        self.client.force_login(admin)
        r = self.client.get(reverse('automation-center'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Scheduler mode')
        self.assertContains(r, 'data_quality')
        self.assertContains(r, 'never')   # the jobs that have not run say so


class SchedulerModeSettingTests(TestCase):
    def test_mode_defaults_are_sane(self):
        from django.conf import settings
        self.assertIn(settings.SCHEDULER_MODE, {'celery', 'builtin', 'external', 'off'})

    def test_celery_task_goes_through_the_same_locked_jobs(self):
        from core.tasks import scheduler_tick_task
        out = scheduler_tick_task()
        self.assertEqual({o['job'] for o in out}, set(scheduler.JOBS))
        self.assertEqual(SchedulerJob.objects.get(name='data_quality').last_trigger, 'celery')
