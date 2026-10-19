import csv
import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from academics.models import Program
from core.models import AuditLog, Profile
from governance.models import Role, RoleAssignment
from governance.tests import Base
from registration.models import Student


def upload(client, text, name='s.csv'):
    return client.post(reverse('student-import'), {'csvfile': SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')})


class ImportExportBase(Base):
    def setUp(self):
        super().setUp()
        self.registrar = User.objects.create_user('reg1', password='pw')
        Profile.objects.update_or_create(user=self.registrar, defaults={'role': 'staff'})
        RoleAssignment.objects.create(user=self.registrar, role=Role.objects.get(code='registrar'))


class ImportAuthorityTests(ImportExportBase):
    def test_only_people_with_student_permissions_may_import_or_export(self):
        for user in (self.teacher, self.student.user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('student-import')).status_code, 403)
            self.assertEqual(self.client.get(reverse('student-export')).status_code, 403)
        it = User.objects.create_user('it1', password='pw')
        RoleAssignment.objects.create(user=it, role=Role.objects.get(code='it_administrator'))
        self.client.force_login(it)
        self.assertEqual(self.client.get(reverse('student-import')).status_code, 403)

    def test_registrar_can_open_the_page(self):
        self.client.force_login(self.registrar)
        self.assertEqual(self.client.get(reverse('student-import')).status_code, 200)

    def test_department_scoped_registrar_cannot_import_into_another_department(self):
        other_prog = Program.objects.create(name='BSEE', code='BSEE', department=self.dept2)
        scoped = User.objects.create_user('reg_scoped', password='pw')
        Profile.objects.update_or_create(user=scoped, defaults={'role': 'staff'})
        RoleAssignment.objects.create(user=scoped, role=Role.objects.get(code='registrar'), scope_type='department', scope_id=self.dept.pk)
        self.client.force_login(scoped)
        r = upload(self.client, 'admission_no,full_name,program_code\nN1,New One,BSEE\nN2,New Two,BSCS\n')
        self.assertContains(r, 'not authorised')
        self.assertFalse(Student.objects.filter(admission_no__in=['N1', 'N2']).exists())


class ImportValidationTests(ImportExportBase):
    def test_valid_file_is_checked_first_and_only_saved_on_confirm(self):
        self.client.force_login(self.registrar)
        r = upload(self.client, 'admission_no,full_name,program_code,status\nA100,Ali Raza,BSCS,active\nA101,Sara Khan,BSCS,active\n')
        self.assertContains(r, 'Confirm and import 2')
        self.assertFalse(Student.objects.filter(admission_no='A100').exists())        # nothing saved yet
        self.client.post(reverse('student-import'), {'confirm': '1'})
        s = Student.objects.get(admission_no='A100')
        self.assertFalse(s.user.is_active)
        self.assertFalse(s.user.has_usable_password())
        self.assertEqual(s.active_program, self.program)
        self.assertTrue(AuditLog.objects.filter(action='STUDENT_IMPORT').exists())

    def test_any_bad_row_blocks_the_whole_file_with_line_numbers(self):
        self.client.force_login(self.registrar)
        text = ('admission_no,full_name,program_code,status,email\n'
                'B1,Good One,BSCS,active,\n'
                'B2,,BSCS,active,\n'
                'B3,Bad Status,BSCS,retired,\n'
                'B4,No Program,NOPE,active,\n'
                'B1,Dup Admission,BSCS,active,\n'
                'B5,Bad Mail,BSCS,active,not-an-email\n')
        r = upload(self.client, text)
        body = r.content.decode()
        for needle in ('full_name is empty', 'retired', 'does not exist', 'duplicate admission_no', 'valid address'):
            self.assertIn(needle, body)
        self.assertNotIn('Confirm and import', body)
        self.assertFalse(Student.objects.filter(admission_no__startswith='B').exists())
        self.client.post(reverse('student-import'), {'confirm': '1'})              # no stored file -> nothing happens
        self.assertFalse(Student.objects.filter(admission_no__startswith='B').exists())

    def test_missing_columns_and_non_csv_are_rejected(self):
        self.client.force_login(self.registrar)
        self.assertContains(upload(self.client, 'foo,bar\n1,2\n'), 'Missing required column')
        r = upload(self.client, 'x', name='s.xlsx')
        self.assertEqual(r.status_code, 302)

    def test_existing_students_program_cannot_be_changed_by_import(self):
        other = Program.objects.create(name='BSEE', code='BSEE', department=self.dept)
        self.client.force_login(self.registrar)
        r = upload(self.client, f'admission_no,full_name,program_code\n{self.student.admission_no},Stu,BSEE\n')
        self.assertContains(r, 'transfer/enrollment workflow')
        self.student.refresh_from_db()
        self.assertEqual(self.student.active_program, self.program)

    def test_update_of_existing_student_changes_only_allowed_fields(self):
        self.client.force_login(self.registrar)
        upload(self.client, f'admission_no,full_name,phone\n{self.student.admission_no},Stu Renamed,0300111\n')
        self.client.post(reverse('student-import'), {'confirm': '1'})
        self.student.refresh_from_db()
        self.assertEqual((self.student.full_name, self.student.phone), ('Stu Renamed', '0300111'))


class ExportTests(ImportExportBase):
    def test_export_neutralises_spreadsheet_formulas_and_is_audited(self):
        Student.objects.filter(pk=self.student.pk).update(full_name='=HYPERLINK("http://evil","x")')
        self.client.force_login(self.registrar)
        r = self.client.get(reverse('student-export'))
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        self.assertTrue(any(row[1].startswith("'=") for row in rows[1:]), rows)
        self.assertTrue(AuditLog.objects.filter(action='STUDENT_EXPORT').exists())

    def test_scoped_registrar_exports_only_their_department(self):
        other_prog = Program.objects.create(name='BSEE', code='BSEE', department=self.dept2)
        Student.objects.create(user=User.objects.create_user('ee1', password='pw'), full_name='EE Kid', admission_no='EE1', program=other_prog)
        scoped = User.objects.create_user('reg_sc2', password='pw')
        Profile.objects.update_or_create(user=scoped, defaults={'role': 'staff'})
        RoleAssignment.objects.create(user=scoped, role=Role.objects.get(code='registrar'), scope_type='department', scope_id=self.dept.pk)
        self.client.force_login(scoped)
        text = self.client.get(reverse('student-export')).content.decode()
        self.assertIn(self.student.admission_no, text)
        self.assertNotIn('EE1', text)
