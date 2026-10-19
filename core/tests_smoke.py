"""Smoke crawl: every URL that needs no arguments, requested (GET) as each kind of
user. A page may redirect, refuse (403/404/405) or render, but it must never crash (5xx)."""
from django.contrib.auth.models import User
from django.urls import URLPattern, URLResolver, get_resolver

from core.models import Profile
from governance.models import Role, RoleAssignment
from governance.tests import Base

SKIP = ('logout', 'webhook', 'cron', 'media', 'download', 'export', 'api/')


def collect(patterns=None, prefix=''):
    out = []
    for p in patterns or get_resolver().url_patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            out += collect(p.url_patterns, route)
        elif isinstance(p, URLPattern) and '<' not in route and '(' not in route and not route.startswith('^'):
            out.append('/' + route)
    return sorted(set(out))


class OfficeUsers:
    def office(self, username, code):
        u = User.objects.create_user(username, password='pw')
        Profile.objects.update_or_create(user=u, defaults={'role': 'staff'})
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code=code))
        return u


class SmokeCrawlTests(OfficeUsers, Base):
    def test_no_page_crashes_for_any_role(self):
        self.client.raise_request_exception = False
        users = {
            'anonymous': None, 'system admin': self.superuser, 'teacher': self.teacher, 'student': self.student.user,
            'registrar': self.office('smk_reg', 'registrar'), 'finance officer': self.office('smk_fin', 'finance_officer'),
            'it admin': self.office('smk_it', 'it_administrator'), 'vice chancellor': self.office('smk_vc', 'vice_chancellor'),
            'exam controller': self.office('smk_ec', 'exam_controller'), 'hr officer': self.office('smk_hr', 'hr_officer'),
        }
        urls = [u for u in collect() if not any(s in u for s in SKIP)]
        self.assertGreater(len(urls), 100)
        crashes = []
        for who, user in users.items():
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in urls:
                try:
                    status = self.client.get(url).status_code
                except Exception as exc:                      # a raised exception is also a crash
                    crashes.append((who, url, type(exc).__name__))
                    continue
                if status >= 500:
                    crashes.append((who, url, status))
        self.assertEqual(crashes, [], f'{len(crashes)} crashing page(s): {crashes[:25]}')


class MissingRecordStateTests(Base):
    def test_student_login_without_student_record_gets_a_clear_message_not_a_crash(self):
        u = User.objects.create_user('orphan', password='pw')
        Profile.objects.update_or_create(user=u, defaults={'role': 'student'})
        self.client.force_login(u)
        with self.assertNoLogs('django.security', level='ERROR'):
            r = self.client.get('/dashboard/', follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No student record is linked')


class DashboardLinkTests(OfficeUsers, Base):
    """Every internal link a user is shown on their dashboard must lead somewhere real."""
    def test_no_dead_links_on_role_dashboards(self):
        import re
        self.client.raise_request_exception = False
        users = {'system admin': self.superuser, 'teacher': self.teacher, 'student': self.student.user,
                 'registrar': self.office('lnk_reg', 'registrar'), 'finance officer': self.office('lnk_fin', 'finance_officer'),
                 'vice chancellor': self.office('lnk_vc', 'vice_chancellor'), 'it admin': self.office('lnk_it', 'it_administrator')}
        dead = []
        for who, user in users.items():
            self.client.force_login(user)
            html = self.client.get('/dashboard/', follow=True).content.decode()
            links = set(re.findall(r'href="(/[^"#?]*)"', html))
            for link in sorted(links):
                if link.startswith(('/static/', '/media/', '/logout')):
                    continue
                code = self.client.get(link).status_code
                if code == 404 or code >= 500:
                    dead.append((who, link, code))
        self.assertEqual(dead, [], f'Dead links: {dead}')
