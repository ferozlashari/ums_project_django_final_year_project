from django.test import TestCase
from django.urls import reverse


class SidebarVsApiUrlNameCollisionTests(TestCase):
    """Real bug: DRF's DefaultRouter auto-generates URL names like
    'course-list' from the registered viewsets, which collided with the
    identically-named human-facing pages in academics/urls.py. The
    result: {% url 'course-list' %} in the sidebar silently resolved to
    the JSON API endpoint instead of the HTML page, for every one of
    Courses/Faculties/Departments/Programs. Fixed by giving the API
    router explicit non-colliding basenames (api-course, api-faculty,
    etc.) - this locks that fix in place.
    """

    def test_human_page_names_resolve_to_academics_app(self):
        self.assertEqual(reverse('course-list'), '/academics/courses/')
        self.assertEqual(reverse('faculty-list'), '/academics/faculties/')
        self.assertEqual(reverse('department-list'), '/academics/departments/')
        self.assertEqual(reverse('program-list'), '/academics/programs/')

    def test_api_endpoints_are_unaffected_and_still_reachable(self):
        self.assertEqual(reverse('api-course-list'), '/api/v1/courses/')
        self.assertEqual(reverse('api-faculty-list'), '/api/v1/faculties/')
        self.assertEqual(reverse('api-department-list'), '/api/v1/departments/')
        self.assertEqual(reverse('api-program-list'), '/api/v1/programs/')

    def test_sidebar_link_for_courses_serves_html_not_json(self):
        from django.contrib.auth.models import User
        admin = User.objects.create_user('urlnametest_admin', password='pw', is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse('course-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(resp['Content-Type'], ('text/html; charset=utf-8', 'text/html'))
