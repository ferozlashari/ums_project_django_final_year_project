"""Authenticated media gateway: private uploads are never fetchable by URL guessing."""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from academics.models import Faculty, Department, Program, Course, CourseSection
from admissions.models import Application
from assignments.models import Assignment, Submission
from core.models import Profile
from governance.models import Role, RoleAssignment
from hostel.models import Hostel, HostelApplication
from hr.models import Staff
from registration.models import Student
from django.utils import timezone
from datetime import timedelta

PDF = b'%PDF-1.4\n%fake\n'
_TMP = tempfile.mkdtemp(prefix='ums_media_test_')


def pdf(name='doc.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


@override_settings(MEDIA_ROOT=_TMP, MEDIA_ACCEL_PREFIX='')
class MediaGatewayTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        faculty = Faculty.objects.create(name='Eng')
        dept = Department.objects.create(name='CS', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Prog', credits=3, program=self.program)

        self.alice = User.objects.create_user('alice', password='pw')
        self.bob = User.objects.create_user('bob', password='pw')
        self.root = User.objects.create_superuser('root', 'r@x.com', 'pw')
        self.stu_a = Student.objects.create(user=self.alice, full_name='Alice', admission_no='A-1', program=self.program, gender='female')
        self.stu_b = Student.objects.create(user=self.bob, full_name='Bob', admission_no='B-1', program=self.program, gender='male')

        # Teachers
        t1 = User.objects.create_user('teach1', password='pw'); Profile.objects.filter(user=t1).update(role='faculty')
        t2 = User.objects.create_user('teach2', password='pw'); Profile.objects.filter(user=t2).update(role='faculty')
        self.teacher1, self.teacher2 = t1, t2
        s1 = Staff.objects.create(user=t1, employee_id='E1', department=dept)
        Staff.objects.create(user=t2, employee_id='E2', department=dept)
        section = CourseSection.objects.create(course=course, code='A', instructor=s1)
        a = Assignment.objects.create(section=section, title='HW', due_date=timezone.now() + timedelta(days=3))

        self.admission = Application.objects.create(applicant=self.alice, program=self.program, full_name='Alice', cnic_copy=pdf('cnic.pdf'))
        self.hostel_app = HostelApplication.objects.create(
            student=self.stu_a, hostel=Hostel.objects.create(name='H', gender='female'), cnic_copy=pdf('h.pdf'))
        self.submission = Submission.objects.create(assignment=a, student=self.stu_a, file=pdf('sub.pdf'))

        # sub-admins (profile role staff, governance-limited)
        self.adm_officer = User.objects.create_user('admoff', password='pw')
        Profile.objects.filter(user=self.adm_officer).update(role='staff')
        RoleAssignment.objects.create(user=self.adm_officer, role=Role.objects.get(code='admission_officer'))
        self.fin_officer = User.objects.create_user('finoff', password='pw')
        Profile.objects.filter(user=self.fin_officer).update(role='staff')
        RoleAssignment.objects.create(user=self.fin_officer, role=Role.objects.get(code='finance_officer'))
        self.plain_staff = User.objects.create_user('plainstaff', password='pw', is_staff=True)
        Profile.objects.filter(user=self.plain_staff).update(role='student')

        self.adm_url = self.admission.cnic_copy.url
        self.host_url = self.hostel_app.cnic_copy.url
        self.sub_url = self.submission.file.url

    def get(self, user, url):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.get(url)

    # --- authentication -------------------------------------------------
    def test_anonymous_is_sent_to_login_not_served(self):
        r = self.get(None, self.adm_url)
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    # --- owner / superuser ---------------------------------------------
    def test_owner_can_download_own_documents(self):
        for url in (self.adm_url, self.host_url, self.sub_url):
            r = self.get(self.alice, url)
            self.assertEqual(r.status_code, 200, url)
            self.assertEqual(b''.join(r.streaming_content), PDF)

    def test_super_admin_can_open_everything(self):
        for url in (self.adm_url, self.host_url, self.sub_url):
            self.assertEqual(self.get(self.root, url).status_code, 200)

    # --- IDOR: another student -----------------------------------------
    def test_another_student_gets_403_on_every_private_file(self):
        for url in (self.adm_url, self.host_url, self.sub_url):
            self.assertEqual(self.get(self.bob, url).status_code, 403, url)

    # --- reviewers ------------------------------------------------------
    def test_admission_officer_sees_admission_docs_only(self):
        self.assertEqual(self.get(self.adm_officer, self.adm_url).status_code, 200)
        self.assertEqual(self.get(self.adm_officer, self.host_url).status_code, 403)   # no hostel permission
        self.assertEqual(self.get(self.adm_officer, self.sub_url).status_code, 403)

    def test_finance_officer_sees_none_of_them(self):
        for url in (self.adm_url, self.host_url, self.sub_url):
            self.assertEqual(self.get(self.fin_officer, url).status_code, 403, url)

    def test_is_staff_flag_alone_is_not_a_wildcard(self):
        for url in (self.adm_url, self.host_url, self.sub_url):
            self.assertEqual(self.get(self.plain_staff, url).status_code, 403, url)

    def test_only_the_section_teacher_can_open_a_submission(self):
        self.assertEqual(self.get(self.teacher1, self.sub_url).status_code, 200)
        self.assertEqual(self.get(self.teacher2, self.sub_url).status_code, 403)
        # a teacher is not an admissions reviewer
        self.assertEqual(self.get(self.teacher1, self.adm_url).status_code, 403)

    # --- hardening ------------------------------------------------------
    def test_path_traversal_is_rejected(self):
        for bad in ('/media/../.secret_key', '/media/%2e%2e/manage.py', '/media/admission_docs/../../manage.py'):
            self.assertIn(self.get(self.root, bad).status_code, (400, 403, 404), bad)

    def test_unmapped_file_is_admin_only(self):
        import os
        os.makedirs(os.path.join(_TMP, 'orphans'), exist_ok=True)
        with open(os.path.join(_TMP, 'orphans', 'x.pdf'), 'wb') as fh:
            fh.write(PDF)
        self.assertEqual(self.get(self.bob, '/media/orphans/x.pdf').status_code, 403)
        self.assertEqual(self.get(self.root, '/media/orphans/x.pdf').status_code, 200)

    def test_missing_file_is_404_for_admin(self):
        self.assertEqual(self.get(self.root, '/media/admission_docs/nope.pdf').status_code, 404)

    def test_pdf_inline_but_html_is_forced_to_download(self):
        r = self.get(self.alice, self.adm_url)
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        import os
        os.makedirs(os.path.join(_TMP, 'profiles'), exist_ok=True)
        with open(os.path.join(_TMP, 'profiles', 'evil.html'), 'w') as fh:
            fh.write('<script>alert(1)</script>')
        r = self.get(self.alice, '/media/profiles/evil.html')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')

    def test_private_cache_headers(self):
        self.assertIn('no-store', self.get(self.alice, self.adm_url)['Cache-Control'])

    @override_settings(MEDIA_ACCEL_PREFIX='/_protected_media/')
    def test_nginx_accel_redirect_only_after_authorisation(self):
        r = self.get(self.alice, self.adm_url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['X-Accel-Redirect'], '/_protected_media/' + self.admission.cnic_copy.name)
        self.assertEqual(self.get(self.bob, self.adm_url).status_code, 403)
        self.assertNotIn('X-Accel-Redirect', self.get(self.bob, self.adm_url))
