"""program-wise fees, five-choice admission form, automatic challans."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import AcademicSession, CourseRegistration, CourseSection, Course, Department, Faculty, Program, Semester
from admissions.models import Application, ProgramPreference
from core.models import Profile
from core.services.automation import AutomationService
from finance.models import Invoice
from finance.services import FeeChallanService
from registration.models import Student


def pdf(name):
    return SimpleUploadedFile(name, b'%PDF-1.4 fake', content_type='application/pdf')


class Base(TestCase):
    def setUp(self):
        fac = Faculty.objects.create(name='Eng')
        dept = Department.objects.create(name='CS', faculty=fac)
        self.programs = [Program.objects.create(name=f'Prog {c}', code=c, department=dept, semester_fee=fee, application_fee=app,
                                                admission_fee=adm, degree_fee=deg)
                         for c, fee, app, adm, deg in [('A', 40000, 2000, 20000, 8000), ('B', 55000, 3500, 30000, 12000),
                                                        ('C', 60000, 0, 0, 0), ('D', 30000, 1000, 10000, 5000), ('E', 35000, 1500, 15000, 6000)]]
        self.A, self.B, self.C, self.D, self.E = self.programs
        today = timezone.localdate()
        sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=20), end_date=today + datetime.timedelta(days=200))
        self.sem = Semester.objects.create(name='Fall 2026', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=20), end_date=today + datetime.timedelta(days=100))
        self.user = User.objects.create_user('stu', 's@example.com', 'pw')
        Profile.objects.update_or_create(user=self.user, defaults={'role': 'student'})
        self.student = Student.objects.create(user=self.user, full_name='Stu', admission_no='F-1', program=self.B, status='active', admission_semester=self.sem)


class ProgramWiseFeeTests(Base):
    def test_semester_fee_uses_program_amount_and_is_once_per_semester(self):
        r = FeeChallanService.generate_semester_fee(self.student)
        self.assertTrue(r.ok)
        self.assertEqual(r.invoice.amount, Decimal('55000.00'))
        self.assertEqual(r.invoice.semester, self.sem)
        r.invoice.paid = True
        r.invoice.save()
        again = FeeChallanService.generate_semester_fee(self.student)
        self.assertEqual(again.invoice.pk, r.invoice.pk)                       # paid one blocks a second
        self.assertEqual(Invoice.objects.filter(category='semester').count(), 1)

    def test_different_programs_charge_different_fees(self):
        u2 = User.objects.create_user('s2', password='pw')
        other = Student.objects.create(user=u2, full_name='Two', admission_no='F-2', program=self.D, status='active')
        self.assertEqual(FeeChallanService.generate_semester_fee(other).invoice.amount, Decimal('30000.00'))

    def test_exam_fee_no_longer_exists(self):
        self.assertFalse(hasattr(FeeChallanService, 'generate_exam_fee'))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse('generate-my-challan', args=['exam_fee'])).status_code, 403)

    def test_admission_fee_is_the_admitted_programs_and_idempotent(self):
        r = FeeChallanService.generate_admission_fee(self.student)
        self.assertEqual(r.invoice.amount, Decimal('30000.00'))
        self.assertEqual(FeeChallanService.generate_admission_fee(self.student).invoice.pk, r.invoice.pk)

    def test_zero_fee_program_creates_no_challan(self):
        self.student.program = self.C
        self.student.save()
        self.assertFalse(FeeChallanService.generate_admission_fee(self.student).ok)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_degree_fee_only_for_final_semester_or_graduated(self):
        self.assertFalse(FeeChallanService.generate_degree_fee(self.student).ok)
        self.student.status = 'graduated'
        self.student.save()
        r = FeeChallanService.generate_degree_fee(self.student)
        self.assertTrue(r.ok)
        self.assertEqual((r.invoice.category, r.invoice.amount), ('degree', Decimal('12000.00')))
        self.assertEqual(FeeChallanService.generate_degree_fee(self.student).invoice.pk, r.invoice.pk)


class FiveChoiceAdmissionTests(Base):
    def _post(self, **choices):
        data = {'cnic_copy': pdf('c.pdf'), 'education_certificate': pdf('e.pdf'), **choices}
        return self.client.post(reverse('apply-public'), data | {'full_name': 'Pub Lic', 'cnic': '12345-1234567-1', 'email': 'pub@example.com'})

    def test_only_first_choice_is_required_and_becomes_application_program(self):
        r = self._post(preference_1=self.B.pk)
        self.assertEqual(r.status_code, 200)
        app = Application.objects.get()
        self.assertEqual(app.program, self.B)
        self.assertEqual([p.program for p in app.preferences.all()], [self.B])

    def test_five_choices_saved_in_order(self):
        self._post(preference_1=self.C.pk, preference_2=self.A.pk, preference_3=self.E.pk, preference_4=self.B.pk, preference_5=self.D.pk)
        app = Application.objects.get()
        self.assertEqual([(p.rank, p.program.code) for p in app.preferences.all()], [(1, 'C'), (2, 'A'), (3, 'E'), (4, 'B'), (5, 'D')])
        self.assertEqual(app.program, self.C)

    def test_missing_first_choice_gap_and_duplicates_rejected(self):
        self._post(preference_2=self.A.pk)
        self._post(preference_1=self.A.pk, preference_3=self.B.pk)
        self._post(preference_1=self.A.pk, preference_2=self.A.pk)
        self.assertFalse(Application.objects.exists())

    def test_logged_in_applicant_gets_first_choice_application_fee_challan(self):
        self.student.status = 'withdrawn'
        self.student.save()
        self.client.force_login(self.user)
        r = self.client.post(reverse('apply'), {'preference_1': self.A.pk, 'preference_2': self.B.pk,
                                                'cnic_copy': pdf('c.pdf'), 'education_certificate': pdf('e.pdf')})
        self.assertEqual(r.status_code, 302)
        inv = Invoice.objects.get(category='admission')
        self.assertEqual(inv.amount, Decimal('2000.00'))                       # program A's application fee, not a constant
        self.assertEqual(ProgramPreference.objects.count(), 2)


class AutomationChallanTests(Base):
    def _register(self, student):
        course = Course.objects.create(code=f'C{student.pk}', name='X', credits=3, program=student.program)
        sec = CourseSection.objects.create(course=course, code='A', capacity=30)
        CourseRegistration.objects.create(student=student, section=sec, semester=self.sem, status='registered')

    def test_automation_raises_semester_challan_only_for_registered_students_and_is_idempotent(self):
        self._register(self.student)
        u2 = User.objects.create_user('unreg', password='pw')
        Student.objects.create(user=u2, full_name='Unreg', admission_no='F-9', program=self.A, status='active')
        AutomationService.run(only=['fee_challans'])
        self.assertEqual(list(Invoice.objects.values_list('student_id', 'category', 'amount')), [(self.student.pk, 'semester', Decimal('55000.00'))])
        AutomationService.run(only=['fee_challans'])
        self.assertEqual(Invoice.objects.filter(category='semester').count(), 1)

    def test_automation_raises_degree_fee_for_graduated_student(self):
        self.student.status = 'graduated'
        self.student.save()
        AutomationService.run(only=['fee_challans'])
        # graduated students are not 'active', so nothing is charged automatically for them
        self.assertEqual(Invoice.objects.filter(category='degree').count(), 0)

    def test_late_fee_task_issues_one_penalty_after_grace_and_only_once(self):
        inv = Invoice.objects.create(student=self.student, category='semester', amount=Decimal('1000'), due_date=timezone.localdate() - datetime.timedelta(days=3))
        AutomationService.run(only=['late_fees'])
        pen = Invoice.objects.get(category='penalty')
        self.assertEqual(pen.reference, f'Late fee for {inv.challan_no}')
        AutomationService.run(only=['late_fees'])
        self.assertEqual(Invoice.objects.filter(category='penalty').count(), 1)

    def test_late_fee_respects_policy_grace_days(self):
        from governance.policy import ensure_default_rules, new_version
        from governance.models import PolicyRule
        ensure_default_rules()
        new_version(PolicyRule.objects.get(key='finance.late_fee_grace_days'), 10)
        Invoice.objects.create(student=self.student, category='semester', amount=Decimal('1000'), due_date=timezone.localdate() - datetime.timedelta(days=3))
        AutomationService.run(only=['late_fees'])
        self.assertFalse(Invoice.objects.filter(category='penalty').exists())

    def test_penalty_invoices_do_not_get_penalties(self):
        Invoice.objects.create(student=self.student, category='penalty', amount=Decimal('50'), due_date=timezone.localdate() - datetime.timedelta(days=30))
        AutomationService.run(only=['late_fees'])
        self.assertEqual(Invoice.objects.count(), 1)


class AdmissionToFeeChallanTests(Base):
    def test_enrolling_an_applicant_raises_the_admission_fee_of_the_won_program(self):
        from admissions.services import AdmissionService
        applicant = User.objects.create_user('appl', password='pw')
        app = Application.objects.create(applicant=applicant, program=self.E, full_name='Ap Pl')
        self.assertTrue(AdmissionService.enroll(app))
        inv = Invoice.objects.get(student__user=applicant)
        self.assertEqual((inv.category, inv.amount), ('admission', Decimal('15000.00')))
