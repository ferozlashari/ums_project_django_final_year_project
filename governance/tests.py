"""permission matrix, teacher lock-out from academic structure,
configurable grade scale, controlled grade corrections, versioned policy."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import Course, CourseSection, Department, Faculty, Program
from core.models import AuditLog, Profile
from exams.grading import validate_bands
from exams.models import ExamSession, GradeEntry, GradeScale, ResultChangeRequest, ResultVersion
from governance.models import PolicyRule, Role, RoleAssignment
from governance.permissions import has_perm
from governance.policy import ensure_default_rules, new_version, resolve
from hr.models import Staff
from registration.models import Student


class Base(TestCase):
    def setUp(self):
        self.faculty = Faculty.objects.create(name='Engineering')
        self.dept = Department.objects.create(name='CS', faculty=self.faculty)
        self.dept2 = Department.objects.create(name='EE', faculty=self.faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=self.dept)
        self.course = Course.objects.create(code='CS101', name='Prog', credits=3, program=self.program)
        self.superuser = User.objects.create_superuser('root', password='pw')
        self.teacher = User.objects.create_user('teach', password='pw')
        Profile.objects.update_or_create(user=self.teacher, defaults={'role': 'faculty'})
        self.staff_rec = Staff.objects.create(user=self.teacher, employee_id='T1', department=self.dept, role='lecturer', hire_date=timezone.localdate())
        self.section = CourseSection.objects.create(course=self.course, code='A', capacity=30, instructor=self.staff_rec)
        su = User.objects.create_user('stud', password='pw')
        self.student = Student.objects.create(user=su, full_name='Stu', admission_no='S1', program=self.program)
        self.exam = ExamSession.objects.create(name='Final', course=self.course, date=timezone.localdate(), max_marks=100)


class PermissionMatrixTests(Base):
    def test_default_roles_are_seeded_and_explicit(self):
        self.assertTrue(Role.objects.get(code='finance_officer').permissions.filter(module='finance', action='reconcile').exists())
        self.assertFalse(Role.objects.get(code='finance_officer').permissions.filter(module='results').exists())
        self.assertFalse(Role.objects.get(code='exam_controller').permissions.filter(module='finance').exists())

    def test_superuser_has_everything_teacher_nothing(self):
        self.assertTrue(has_perm(self.superuser, 'security', 'configure'))
        self.assertFalse(has_perm(self.teacher, 'courses', 'edit'))
        self.assertFalse(has_perm(self.student.user, 'courses', 'view'))

    def test_subadmin_limited_to_role_even_if_is_staff(self):
        u = User.objects.create_user('adm', password='pw', is_staff=True)
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code='admission_officer'))
        self.assertTrue(has_perm(u, 'admissions', 'verify'))
        self.assertFalse(has_perm(u, 'admissions', 'approve'))   # selection is the committee's decision
        self.assertFalse(has_perm(u, 'admissions', 'publish'))
        self.assertFalse(has_perm(u, 'finance', 'view'))
        self.assertFalse(has_perm(u, 'results', 'edit'))

    def test_scope_limits_department(self):
        u = User.objects.create_user('hod', password='pw')
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code='hod'), scope_type='department', scope_id=self.dept.pk)
        self.assertTrue(has_perm(u, 'sections', 'assign', department=self.dept))
        self.assertFalse(has_perm(u, 'sections', 'assign', department=self.dept2))
        self.assertTrue(has_perm(u, 'sections', 'assign', program=self.program))

    def test_temporary_assignment_expires_and_can_be_revoked(self):
        u = User.objects.create_user('temp', password='pw')
        today = timezone.localdate()
        a = RoleAssignment.objects.create(user=u, role=Role.objects.get(code='registrar'), end_date=today - datetime.timedelta(days=1))
        self.assertFalse(has_perm(u, 'students', 'view'))
        a.end_date = today + datetime.timedelta(days=5)
        a.save()
        self.assertTrue(has_perm(u, 'students', 'view'))
        a.is_active = False
        a.save()
        self.assertFalse(has_perm(u, 'students', 'view'))

    def test_inactive_role_grants_nothing(self):
        u = User.objects.create_user('inact', password='pw')
        role = Role.objects.get(code='registrar')
        RoleAssignment.objects.create(user=u, role=role)
        role.is_active = False
        role.save()
        self.assertFalse(has_perm(u, 'students', 'view'))


class TeacherCannotChangeStructureTests(Base):
    def test_teacher_blocked_from_course_section_program_writes(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('course-add')).status_code, 403)
        self.assertEqual(self.client.post(reverse('course-edit', args=[self.course.pk]), {'code': 'X'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('section-add')).status_code, 403)
        self.assertEqual(self.client.get(reverse('section-edit', args=[self.section.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('program-add')).status_code, 403)
        self.course.refresh_from_db()
        self.assertEqual(self.course.code, 'CS101')

    def test_superuser_can_open_course_form(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse('course-add')).status_code, 200)

    def test_subadmin_perms_are_exactly_their_role(self):
        u = User.objects.create_user('acad', password='pw')
        Profile.objects.update_or_create(user=u, defaults={'role': 'staff'})
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse('course-add')).status_code, 403)
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code='academic_admin'))
        self.assertEqual(self.client.get(reverse('course-add')).status_code, 200)
        self.assertEqual(self.client.post(reverse('grade-scale'), {}).status_code, 403)


class SecurityCenterTests(Base):
    def test_only_superuser_reaches_security_center(self):
        for name in ('security-center', 'role-list', 'role-assignments', 'policy-center', 'subadmin-create'):
            self.client.force_login(self.teacher)
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
            self.client.force_login(self.superuser)
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_create_subadmin_is_not_staff_and_gets_role(self):
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('subadmin-create'), {
            'username': 'fin1', 'password': 'Str0ngPass!!', 'role': Role.objects.get(code='finance_officer').pk, 'scope_type': 'university'})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username='fin1')
        self.assertFalse(u.is_staff or u.is_superuser)
        self.assertTrue(has_perm(u, 'finance', 'view'))
        self.assertFalse(has_perm(u, 'results', 'view'))
        self.assertTrue(AuditLog.objects.filter(action='USER_CREATED').exists())

    def test_role_matrix_save_adds_and_removes_with_audit(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('role-add'), {'name': 'Library Clerk', 'code': 'library_clerk', 'is_active': 'on',
                                               'perm_library__view': 'on', 'perm_library__create': 'on'})
        role = Role.objects.get(code='library_clerk')
        self.assertEqual(role.permission_pairs(), {('library', 'view'), ('library', 'create')})
        self.client.post(reverse('role-edit', args=[role.pk]), {'name': 'Library Clerk', 'code': 'library_clerk', 'is_active': 'on', 'perm_library__view': 'on'})
        self.assertEqual(role.permission_pairs(), {('library', 'view')})
        self.assertTrue(AuditLog.objects.filter(action='ROLE_CHANGED').exists())

    def test_system_role_cannot_be_deleted(self):
        self.client.force_login(self.superuser)
        role = Role.objects.get(code='registrar')
        self.client.post(reverse('role-delete', args=[role.pk]))
        self.assertTrue(Role.objects.filter(pk=role.pk).exists())


class GradeScaleTests(Base):
    def _entry(self, marks):
        GradeEntry.objects.filter(student=self.student).delete()
        return GradeEntry.objects.create(student=self.student, exam=self.exam, marks=marks)

    def test_default_nine_grade_scale(self):
        expect = {95: ('A+', 4.0), 87: ('A', 4.0), 82: ('B+', 3.5), 77: ('B', 3.0), 72: ('C+', 2.5),
                  67: ('C', 2.0), 62: ('D+', 1.5), 55: ('D', 1.0), 49: ('F', 0.0), 0: ('F', 0.0)}
        for m, (letter, gp) in expect.items():
            e = self._entry(m)
            self.assertEqual((e.letter_grade, e.grade_point, e.grade), (letter, gp, letter), m)

    def test_pass_fail_and_improvement_follow_scale(self):
        self.assertEqual(self._entry(50).status, 'pass')
        f = self._entry(49)
        self.assertEqual(f.status, 'fail')
        self.assertTrue(f.can_apply_retake)
        d = self._entry(55)
        self.assertTrue(d.can_apply_improvement and not d.can_apply_retake)
        self.assertFalse(self._entry(90).can_apply_improvement)

    def test_admin_changes_scale_new_exams_use_it_old_keep_theirs(self):
        old_entry = self._entry(75)
        self.assertEqual(old_entry.letter_grade, 'B')
        self.client.force_login(self.superuser)
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        rows = {'name': 'Strict', 'effective_from': tomorrow.isoformat()}
        for i, (g, mn, gp, p) in enumerate([('A', 80, 4, 1), ('B', 60, 3, 1), ('F', 0, 0, 0)]):
            rows.update({f'grade_{i}': g, f'min_{i}': mn, f'gp_{i}': gp})
            if p:
                rows[f'pass_{i}'] = 'on'
        self.assertEqual(self.client.post(reverse('grade-scale'), rows).status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action='GRADE_SCALE_CHANGED').exists())
        self.assertEqual(GradeEntry.objects.get(pk=old_entry.pk).letter_grade, 'B')   # old exam date -> old scale
        later = ExamSession.objects.create(name='Later', course=self.course, date=tomorrow + datetime.timedelta(days=5), max_marks=100)
        new = GradeEntry.objects.create(student=self.student, exam=later, marks=75)
        self.assertEqual((new.letter_grade, new.grade_point), ('B', 3.0))
        e2 = GradeEntry.objects.create(student=self.student, exam=ExamSession.objects.create(name='L2', course=self.course, date=tomorrow, max_marks=100), marks=85)
        self.assertEqual(e2.letter_grade, 'A')

    def test_invalid_scales_rejected(self):
        self.assertTrue(validate_bands([{'grade': 'A', 'min_percent': 50, 'grade_point': 4, 'is_pass': True},
                                        {'grade': 'F', 'min_percent': 10, 'grade_point': 0, 'is_pass': False}]))
        self.assertTrue(validate_bands([{'grade': 'A', 'min_percent': 50, 'grade_point': 1, 'is_pass': True},
                                        {'grade': 'B', 'min_percent': 20, 'grade_point': 3, 'is_pass': True},
                                        {'grade': 'F', 'min_percent': 0, 'grade_point': 0, 'is_pass': False}]))
        self.assertFalse(validate_bands([{'grade': 'P', 'min_percent': 50, 'grade_point': 2, 'is_pass': True},
                                         {'grade': 'F', 'min_percent': 0, 'grade_point': 0, 'is_pass': False}]))

    def test_teacher_can_view_but_not_change_scale(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('grade-scale')).status_code, 200)
        self.assertEqual(self.client.post(reverse('grade-scale'), {'grade_0': 'A', 'min_0': 0, 'gp_0': 4}).status_code, 403)
        self.assertFalse(GradeScale.objects.exists())


class GradeCorrectionTests(Base):
    def setUp(self):
        super().setUp()
        from academics.models import AcademicSession, CourseRegistration, Semester
        today = timezone.localdate()
        sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=300))
        sem = Semester.objects.create(name='Fall', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=60))
        CourseRegistration.objects.create(student=self.student, section=self.section, semester=sem, status='registered')
        self.entry = GradeEntry.objects.create(student=self.student, exam=self.exam, midterm_marks=10, final_marks=20)
        GradeEntry.objects.filter(pk=self.entry.pk).update(entered_at=timezone.now() - datetime.timedelta(days=400))
        self.entry.refresh_from_db()

    def test_locked_entry_sends_teacher_to_correction_request(self):
        self.client.force_login(self.teacher)
        r = self.client.get(reverse('grade-edit', args=[self.entry.pk]))
        self.assertRedirects(r, reverse('grade-correction-request', args=[self.entry.pk]), fetch_redirect_response=False)

    def test_request_does_not_change_result_until_approved(self):
        self.client.force_login(self.teacher)
        before = self.entry.marks
        r = self.client.post(reverse('grade-correction-request', args=[self.entry.pk]),
                             {'midterm_marks': '30', 'final_marks': '40', 'reason': 'Marks were mis-added on the paper'})
        self.assertEqual(r.status_code, 302)
        req = ResultChangeRequest.objects.get()
        self.assertEqual(req.status, 'pending')
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.marks, before)
        self.assertEqual(self.client.post(reverse('grade-correction-decide', args=[req.pk, 'approve'])).status_code, 403)

    def test_officer_approval_applies_preserves_history_and_audits(self):
        req = ResultChangeRequest.objects.create(grade_entry=self.entry, requested_by=self.teacher, reason='Recount found error',
                                                 old_marks=self.entry.marks, old_grade=self.entry.letter_grade,
                                                 new_midterm_marks=Decimal('30'), new_final_marks=Decimal('40'))
        officer = User.objects.create_user('exam1', password='pw')
        RoleAssignment.objects.create(user=officer, role=Role.objects.get(code='exam_controller'))
        self.client.force_login(officer)
        self.assertEqual(self.client.post(reverse('grade-correction-decide', args=[req.pk, 'approve'])).status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.marks, self.entry.letter_grade), (Decimal('70.00'), 'C+'))
        self.assertEqual(ResultVersion.objects.get(grade_entry=self.entry).marks, Decimal('30.00'))
        self.assertTrue(AuditLog.objects.filter(action='RESULT_CORRECTED').exists())
        req.refresh_from_db()
        self.assertEqual((req.status, req.reviewed_by), ('approved', officer))

    def test_user_without_result_approve_permission_cannot_decide(self):
        req = ResultChangeRequest.objects.create(grade_entry=self.entry, requested_by=self.teacher, reason='xxxxxxxxxxx',
                                                 old_marks=self.entry.marks, new_final_marks=Decimal('40'))
        fin = User.objects.create_user('fin', password='pw')
        RoleAssignment.objects.create(user=fin, role=Role.objects.get(code='finance_officer'))
        self.client.force_login(fin)
        self.assertEqual(self.client.post(reverse('grade-correction-decide', args=[req.pk, 'approve'])).status_code, 403)

    def test_other_teacher_cannot_request_correction(self):
        t2 = User.objects.create_user('t2', password='pw')
        Profile.objects.update_or_create(user=t2, defaults={'role': 'faculty'})
        Staff.objects.create(user=t2, employee_id='T2', department=self.dept, role='lecturer', hire_date=timezone.localdate())
        self.client.force_login(t2)
        self.assertEqual(self.client.get(reverse('grade-correction-request', args=[self.entry.pk])).status_code, 403)

    def test_out_of_range_correction_rejected(self):
        self.client.force_login(self.teacher)
        self.client.post(reverse('grade-correction-request', args=[self.entry.pk]), {'final_marks': '999', 'reason': 'this is a long reason'})
        self.assertFalse(ResultChangeRequest.objects.exists())

    def test_published_result_is_locked_even_when_fresh(self):
        from academics.models import AcademicSession, CourseRegistration, Semester
        from exams.models import ResultPublication
        today = timezone.localdate()
        sess = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=5), end_date=today + datetime.timedelta(days=100))
        sem = Semester.objects.create(name='Fall', session=sess, semester_number=1, start_date=today - datetime.timedelta(days=5), end_date=today + datetime.timedelta(days=100))
        reg = CourseRegistration.objects.create(student=self.student, section=self.section, semester=sem, status='registered')
        exam = ExamSession.objects.create(name='Q', course=self.course, semester=sem, date=today, max_marks=100)
        e = GradeEntry.objects.create(student=self.student, exam=exam, registration=reg, final_marks=30)
        self.assertFalse(e.is_locked)
        ResultPublication.objects.create(registration=reg, status='published')
        e = GradeEntry.objects.get(pk=e.pk)
        self.assertTrue(e.is_published and e.is_locked)


class PolicyVersioningTests(Base):
    def test_versions_kept_and_most_specific_scope_wins(self):
        ensure_default_rules()
        rule = PolicyRule.objects.get(key='attendance.minimum_percent')
        today = timezone.localdate()
        self.assertEqual(resolve('attendance.minimum_percent', default=75), 75)
        new_version(rule, 75, effective_from=today - datetime.timedelta(days=30))
        new_version(rule, 80, scope_type='program', scope_id=self.program.pk, effective_from=today - datetime.timedelta(days=1))
        self.assertEqual(resolve('attendance.minimum_percent', program=self.program), 80)
        self.assertEqual(resolve('attendance.minimum_percent'), 75)
        new_version(rule, 85, scope_type='program', scope_id=self.program.pk, effective_from=today)
        self.assertEqual(resolve('attendance.minimum_percent', program=self.program), 85)
        self.assertEqual(rule.versions.count(), 3)
        new_version(rule, 90, scope_type='program', scope_id=self.program.pk, effective_from=today + datetime.timedelta(days=30))
        self.assertEqual(resolve('attendance.minimum_percent', program=self.program), 85)

    def test_policy_center_creates_version_and_audits(self):
        ensure_default_rules()
        rule = PolicyRule.objects.get(key='attendance.minimum_percent')
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('policy-center'), {'rule': rule.pk, 'value': '80', 'scope_type': 'university',
                                                        'effective_from': timezone.localdate().isoformat(), 'reason': 'Board decision'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(resolve('attendance.minimum_percent'), 80)
        self.assertTrue(AuditLog.objects.filter(action='POLICY_CHANGED').exists())

    def test_invalid_value_rejected(self):
        ensure_default_rules()
        rule = PolicyRule.objects.get(key='attendance.minimum_percent')
        self.client.force_login(self.superuser)
        r = self.client.post(reverse('policy-center'), {'rule': rule.pk, 'value': 'abc', 'scope_type': 'university',
                                                        'effective_from': timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(rule.versions.count(), 0)


# ---------------------------------------------------------------------------
# Office-based governance, separation of duties, break-glass, visibility pages
# ---------------------------------------------------------------------------
from governance.constants import DEFAULT_ROLES, SOD_RULES
from governance.permissions import authority_perm, all_sod_violations, sod_conflicts, user_sod_conflicts


def _holder(username, role_code, **kw):
    u = User.objects.create_user(username, password='pw')
    RoleAssignment.objects.create(user=u, role=Role.objects.get(code=role_code), **kw)
    return u


def grant_emergency(user, minutes=30):
    from governance.models import EmergencyAccess
    return EmergencyAccess.objects.create(user=user, reason='Test: office vacant, urgent decision needed',
                                          expires_at=timezone.now() + datetime.timedelta(minutes=minutes))


class OfficeRoleCatalogueTests(Base):
    def test_every_default_role_is_installed_with_an_office(self):
        for code in DEFAULT_ROLES:
            r = Role.objects.get(code=code)
            self.assertTrue(r.permissions.exists(), code)
        from governance.seed import ensure_default_roles
        ensure_default_roles()
        for code in DEFAULT_ROLES:
            self.assertTrue(Role.objects.get(code=code).office, code)

    def test_no_default_role_bundles_conflicting_duties(self):
        for code, (_, _, perms) in DEFAULT_ROLES.items():
            pairs = {(m, a) for m, acts in perms.items() for a in acts}
            self.assertEqual(sod_conflicts(pairs), [], code)

    def test_required_offices_exist(self):
        for code in ['chancellor', 'vice_chancellor', 'registrar', 'dean', 'hod', 'admission_officer', 'exam_controller',
                     'finance_officer', 'finance_manager', 'hr_officer', 'librarian', 'hostel_officer',
                     'transport_officer', 'it_administrator']:
            self.assertTrue(Role.objects.filter(code=code).exists(), code)

    def test_it_admin_cannot_decide_university_matters(self):
        it = _holder('itadm', 'it_administrator')
        self.assertTrue(has_perm(it, 'security', 'configure'))
        for module, action in [('admissions', 'approve'), ('results', 'publish'), ('finance', 'approve'), ('finance', 'view')]:
            self.assertFalse(has_perm(it, module, action), (module, action))

    def test_finance_officer_cannot_approve_and_exam_officer_cannot_publish(self):
        fo = _holder('fo', 'finance_officer')
        eo = _holder('eo', 'exam_officer')
        self.assertFalse(has_perm(fo, 'finance', 'approve'))
        self.assertFalse(has_perm(fo, 'results', 'view'))
        self.assertTrue(has_perm(eo, 'results', 'approve'))
        self.assertFalse(has_perm(eo, 'results', 'publish'))

    def test_executive_roles_are_oversight_not_crud(self):
        vc = _holder('vc', 'vice_chancellor')
        self.assertTrue(has_perm(vc, 'executive', 'view'))
        self.assertFalse(has_perm(vc, 'students', 'edit'))
        self.assertFalse(has_perm(vc, 'finance', 'approve'))

    def test_hod_scope_is_one_department(self):
        hod = _holder('hodcs', 'hod', scope_type='department', scope_id=self.dept.pk)
        self.assertTrue(has_perm(hod, 'results', 'verify', department=self.dept))
        self.assertFalse(has_perm(hod, 'results', 'verify', department=self.dept2))
        self.assertFalse(has_perm(hod, 'finance', 'view'))


class SeparationOfDutiesTests(Base):
    def test_conflicting_second_role_is_refused_by_the_form(self):
        from governance.forms import AssignmentForm
        u = _holder('pers', 'finance_officer')
        form = AssignmentForm({'user': u.pk, 'role': Role.objects.get(code='finance_manager').pk,
                               'scope_type': 'university'})
        self.assertFalse(form.is_valid())
        self.assertIn('Separation of duties', str(form.errors))

    def test_non_conflicting_second_role_is_allowed(self):
        from governance.forms import AssignmentForm
        u = _holder('pers2', 'librarian')
        form = AssignmentForm({'user': u.pk, 'role': Role.objects.get(code='hostel_officer').pk, 'scope_type': 'university'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_superuser_cannot_be_given_office_roles(self):
        from governance.forms import AssignmentForm
        form = AssignmentForm({'user': self.superuser.pk, 'role': Role.objects.get(code='registrar').pk, 'scope_type': 'university'})
        self.assertFalse(form.is_valid())

    def test_role_editor_refuses_a_conflicting_bundle(self):
        self.client.force_login(self.superuser)
        data = {'name': 'Mega', 'code': 'mega', 'description': '', 'is_active': 'on',
                'perm_finance__approve': 'on', 'perm_finance__create': 'on'}
        self.client.post(reverse('role-add'), data)
        self.assertFalse(Role.objects.filter(code='mega').exists())

    def test_violation_report_finds_people_with_legacy_conflicts(self):
        u = _holder('legacy', 'finance_officer')
        RoleAssignment.objects.create(user=u, role=Role.objects.get(code='finance_manager'))   # bypass the form
        self.assertEqual([x[0] for x in all_sod_violations()], [u])
        self.assertTrue(user_sod_conflicts(u))


class BreakGlassTests(Base):
    def test_superuser_without_an_emergency_grant_gets_nothing(self):
        self.assertEqual(authority_perm(self.superuser, 'finance', 'approve'), (False, False))

    def test_expired_or_revoked_grant_stops_working(self):
        g = grant_emergency(self.superuser)
        self.assertEqual(authority_perm(self.superuser, 'finance', 'approve'), (True, True))
        g.revoked_at = timezone.now(); g.save()
        self.assertEqual(authority_perm(self.superuser, 'finance', 'approve'), (False, False))
        g2 = grant_emergency(self.superuser, minutes=-5)
        self.assertEqual(authority_perm(self.superuser, 'finance', 'approve'), (False, False))

    def test_emergency_page_requires_a_real_reason_and_caps_duration(self):
        from governance.models import EmergencyAccess
        self.client.force_login(self.superuser)
        self.client.post(reverse('emergency-access'), {'reason': 'short', 'minutes': 30})
        self.assertFalse(EmergencyAccess.objects.exists())
        self.client.post(reverse('emergency-access'), {'reason': 'Registrar post is vacant until October 15', 'minutes': 600})
        self.assertFalse(EmergencyAccess.objects.exists())
        self.client.post(reverse('emergency-access'), {'reason': 'Registrar post is vacant until October 15', 'minutes': 60})
        self.assertEqual(EmergencyAccess.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='EMERGENCY_ACCESS_GRANTED').exists())
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('emergency-access')).status_code, 403)

    def test_superuser_acts_only_when_no_office_holder_exists(self):
        grant_emergency(self.superuser)
        ok, glass = authority_perm(self.superuser, 'finance', 'approve')
        self.assertEqual((ok, glass), (True, True))
        _holder('fm', 'finance_manager')
        self.assertEqual(authority_perm(self.superuser, 'finance', 'approve'), (False, False))

    def test_office_holder_is_never_break_glass(self):
        fm = _holder('fm2', 'finance_manager')
        self.assertEqual(authority_perm(fm, 'finance', 'approve'), (True, False))


class VisibilityPageTests(Base):
    def test_everyone_can_open_map_and_my_access(self):
        self.client.force_login(self.student.user)
        for name in ('governance-map', 'my-access'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_student_cannot_see_who_holds_roles(self):
        _holder('secret', 'registrar')
        self.client.force_login(self.student.user)
        self.assertNotContains(self.client.get(reverse('governance-map')), 'secret')

    def test_matrix_needs_security_or_audit_view(self):
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(reverse('permission-matrix')).status_code, 403)
        self.client.force_login(_holder('aud', 'read_only_auditor'))
        self.assertEqual(self.client.get(reverse('permission-matrix')).status_code, 200)

    def test_executive_dashboard_is_for_oversight_roles(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('executive-dashboard')).status_code, 403)
        self.client.force_login(_holder('vc2', 'vice_chancellor'))
        self.assertEqual(self.client.get(reverse('executive-dashboard')).status_code, 200)


class GuardianIsOptionalTests(Base):
    def test_guardian_option_hidden_by_default(self):
        self.assertNotContains(self.client.get(reverse('register')), 'value="guardian"')

    def test_guardian_option_appears_when_enabled(self):
        from core.models import SiteSettings
        s = SiteSettings.load()
        s.enable_guardian_portal = True
        s.save()
        self.assertContains(self.client.get(reverse('register')), 'value="guardian"')


class ResultPublicationSeparationTests(Base):
    """Three different people must verify, approve and publish one result."""
    def _publication(self):
        from academics.models import AcademicSession, CourseRegistration, Semester
        from exams.models import ResultPublication
        today = timezone.localdate()
        session = AcademicSession.objects.create(year='2026-2027', start_date=today - datetime.timedelta(days=30),
                                                 end_date=today + datetime.timedelta(days=300))
        sem = Semester.objects.create(name='Fall 2026', session=session, semester_number=1,
                                      start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=60))
        reg = CourseRegistration.objects.create(student=self.student, section=self.section, semester=sem, status='registered')
        return ResultPublication.objects.create(registration=reg, status='teacher_submitted')

    def test_same_person_cannot_do_two_stages_and_superuser_is_locked_out(self):
        from core.services.role_automation import ResultWorkflowService as S
        from django.core.exceptions import PermissionDenied
        pub = self._publication()
        hod = _holder('hodx', 'hod', scope_type='department', scope_id=self.dept.pk)
        eo = _holder('eox', 'exam_officer')
        ctrl = _holder('ctlx', 'exam_controller')
        with self.assertRaises(PermissionDenied):
            S.advance(eo, pub)                       # exam officer cannot do the department stage
        self.assertEqual(S.advance(hod, pub), 'department_verified')
        pub.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            S.advance(self.superuser, pub)           # office holders exist -> no override by the system owner
        self.assertEqual(S.advance(eo, pub), 'exam_verified')
        pub.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            S.advance(eo, pub)                       # exam officer cannot publish
        self.assertEqual(S.advance(ctrl, pub), 'published')


class ProvisioningTests(Base):
    def _post(self, user, role_code, username):
        self.client.force_login(user)
        return self.client.post(reverse('provision-account'), {
            'username': username, 'password': 'Str0ng-Pass-9', 'role': Role.objects.get(code=role_code).pk, 'scope_type': 'university'})

    def test_people_without_provisioning_authority_are_refused(self):
        self.assertEqual(self._post(self.teacher, 'registrar', 'x1').status_code, 403)
        self.assertEqual(self._post(_holder('fo5', 'finance_officer'), 'finance_manager', 'x2').status_code, 403)

    def test_office_heads_create_only_their_own_roles(self):
        fm = _holder('fm5', 'finance_manager')
        self._post(fm, 'finance_officer', 'newfo')
        self.assertTrue(RoleAssignment.objects.filter(user__username='newfo', role__code='finance_officer', granted_by=fm).exists())
        self._post(fm, 'registrar', 'badreg')                          # not under the Finance Manager
        self.assertFalse(User.objects.filter(username='badreg').exists())
        self._post(fm, 'it_administrator', 'badit')
        self.assertFalse(User.objects.filter(username='badit').exists())

    def test_it_admin_can_create_technical_accounts_only(self):
        it = _holder('it5', 'it_administrator')
        self._post(it, 'security_administrator', 'newsec')
        self.assertTrue(User.objects.filter(username='newsec').exists())
        self._post(it, 'vice_chancellor', 'badvc')
        self.assertFalse(User.objects.filter(username='badvc').exists())

    def test_new_account_gets_no_django_staff_or_superuser_flag(self):
        self._post(_holder('vc5', 'vice_chancellor'), 'registrar', 'newreg')
        u = User.objects.get(username='newreg')
        self.assertFalse(u.is_staff or u.is_superuser)
