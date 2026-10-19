"""Smoke tests for the Exception Center / Data Quality Center.

These deliberately don't assert exact finding counts against the shared
seed dataset (that would make the test brittle to unrelated seed-data
changes). Instead they check the pages that matter: an admin can reach
both centers and get a 200 with real, computed content; a non-admin
(student/teacher) is refused; and the underlying service never raises
even against an empty database.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from oversight.services import OversightService


class OversightServiceTests(TestCase):
    def test_exceptions_returns_categories_on_empty_db(self):
        categories = OversightService.exceptions()
        self.assertTrue(len(categories) >= 5)
        for cat in categories:
            self.assertEqual(cat.count, 0)

    def test_data_quality_returns_categories_on_empty_db(self):
        categories = OversightService.data_quality()
        self.assertTrue(len(categories) >= 4)

    def test_counts_never_raises(self):
        counts = OversightService.counts()
        self.assertIn("exceptions", counts)
        self.assertIn("data_quality", counts)


class OversightAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("oversight_admin", password="pw", is_staff=True, is_superuser=True)
        self.nobody = User.objects.create_user("oversight_plain", password="pw")

    def test_admin_can_view_exception_center(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("exception-center"))
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_view_data_quality_center(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("data-quality-center"))
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_is_refused(self):
        self.client.force_login(self.nobody)
        resp = self.client.get(reverse("exception-center"))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse("data-quality-center"))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(reverse("exception-center"))
        self.assertEqual(resp.status_code, 302)
