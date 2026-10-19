"""Data Entry Hub: permissions, audit, inline formsets, logins/roles, and the login-creating forms."""
import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.urls import reverse

from academics.models import (AcademicSession, Course, CourseRegistration, Curriculum, CurriculumCourse,
                              CurriculumSemester, Semester)
from core.models import AuditLog, Profile
from core.tests_role_automation import Base
from exams.models import AssessmentComponent, AssessmentScheme
from governance.models import Role, RolePermission, RoleAssignment
from hr.models import Staff
from registration.models import Enrollment, Student


class SetupBase(Base):
    def operator(self, name, grants):
        u = self.user(name, 'staff')
        role = Role.objects.create(code=f'r_{name}', name=name)
        for module, action in grants:
            RolePermission.objects.create(role=role, module=module, action=action)
        RoleAssignment.objects.create(user=u, role=role)
        return u

    def msgs(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]


class PermissionTests(SetupBase):
    def test_super_admin_sees_hub_and_every_list(self):
        self.client.force_login(self.root)
        self.assertContains(self.client.get('/setup/'), 'Data Entry Hub')
        for key in ('sessions', 'semesters', 'curricula', 'curriculum-semesters', 'enrollments', 'timeslots', 'schemes',
                    'fee-policies', 'entry-tests', 'applications'):
            self.assertEqual(self.client.get(f'/setup/{key}/').status_code, 200, key)
            self.assertEqual(self.client.get(f'/setup/{key}/add/').status_code, 200, key)

    def test_unknown_key_is_404(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/setup/nope/').status_code, 404)

    def test_students_teachers_and_plain_staff_are_refused(self):
        plain = User.objects.create_user('plain_staff2', password='pw', is_staff=True)
        for who in (self.alice.user, self.t1.user, plain):
            self.client.force_login(who)
            self.assertEqual(self.client.get('/setup/').status_code, 403)
            self.assertEqual(self.client.get('/setup/semesters/').status_code, 403)
            self.assertEqual(self.client.post('/setup/semesters/add/', {}).status_code, 403)

    def test_each_screen_needs_its_own_module_permission(self):
        op = self.operator('currop', [('curriculum', 'view'), ('curriculum', 'create')])
        self.client.force_login(op)
        self.assertEqual(self.client.get('/setup/curricula/add/').status_code, 200)
        self.assertEqual(self.client.get('/setup/semesters/add/').status_code, 403)      # programs module
        self.assertEqual(self.client.get('/setup/schemes/').status_code, 403)            # grade_policy module
        self.assertEqual(self.client.get('/setup/curricula/').status_code, 200)

    def test_view_only_role_cannot_add_or_edit(self):
        op = self.operator('viewer2', [('programs', 'view')])
        self.client.force_login(op)
        self.assertEqual(self.client.get('/setup/sessions/').status_code, 200)
        self.assertNotContains(self.client.get('/setup/sessions/'), '+ Add')
        self.assertEqual(self.client.get('/setup/sessions/add/').status_code, 403)

    def test_scoped_role_limited_to_department_cannot_use_university_screens(self):
        u = self.user('scoped', 'staff')
        role = Role.objects.create(code='r_scoped', name='scoped')
        RolePermission.objects.create(role=role, module='programs', action='create')
        RoleAssignment.objects.create(user=u, role=role, scope_type='department', scope_id=self.dept.pk)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/setup/sessions/add/').status_code, 403)


class RecordEntryTests(SetupBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.root)

    def test_session_and_semester_with_datetime_fields(self):
        r = self.client.post('/setup/sessions/add/', {'year': '2027-2028', 'start_date': '2027-09-01', 'end_date': '2028-08-31'})
        self.assertEqual(r.status_code, 302)
        sess = AcademicSession.objects.get(year='2027-2028')
        r = self.client.post('/setup/semesters/add/', {
            'name': 'Fall 2027', 'session': sess.pk, 'semester_number': 1, 'start_date': '2027-09-06', 'end_date': '2028-01-14',
            'registration_open': '2027-08-24T09:00', 'registration_close': '2027-09-13T17:00',
            'drop_deadline': '', 'exam_registration_open': '', 'exam_registration_close': ''})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        sem = Semester.objects.get(name='Fall 2027')
        from django.utils import timezone
        self.assertEqual(timezone.localtime(sem.registration_close).strftime('%Y-%m-%d %H:%M'), '2027-09-13 17:00')   # stored as UTC

    def test_invalid_semester_shows_errors_and_saves_nothing(self):
        n = Semester.objects.count()
        r = self.client.post('/setup/semesters/add/', {'name': '', 'session': '', 'start_date': 'x', 'end_date': ''})
        self.assertEqual(r.status_code, 200); self.assertTrue(r.context['form'].errors)
        self.assertEqual(Semester.objects.count(), n)

    def inline_prefix(self, url):
        return self.client.get(url).context['formset'].prefix

    def test_curriculum_with_inline_semesters_then_courses(self):
        pre = self.inline_prefix('/setup/curricula/add/')
        r = self.client.post('/setup/curricula/add/', {
            'program': self.program.pk, 'name': 'BSCS Curriculum 2027', 'version': '2027', 'total_credits': 130, 'is_active': 'on',
            f'{pre}-TOTAL_FORMS': 1, f'{pre}-INITIAL_FORMS': 0, f'{pre}-MIN_NUM_FORMS': 0, f'{pre}-MAX_NUM_FORMS': 1000,
            f'{pre}-0-semester_number': 1, f'{pre}-0-title': 'Semester 1', f'{pre}-0-credits_required': 9})
        self.assertEqual(r.status_code, 302, r.context['form'].errors if r.status_code == 200 else '')
        cur = Curriculum.objects.get(name='BSCS Curriculum 2027')
        self.assertEqual(cur.semesters.count(), 1)
        cs = cur.semesters.get()
        pre2 = self.inline_prefix(f'/setup/curriculum-semesters/{cs.pk}/edit/')
        c1 = self.sec1.course
        r = self.client.post(f'/setup/curriculum-semesters/{cs.pk}/edit/', {
            'curriculum': cur.pk, 'semester_number': 1, 'title': 'Semester 1', 'credits_required': 9,
            f'{pre2}-TOTAL_FORMS': 1, f'{pre2}-INITIAL_FORMS': 0, f'{pre2}-MIN_NUM_FORMS': 0, f'{pre2}-MAX_NUM_FORMS': 1000,
            f'{pre2}-0-course': c1.pk, f'{pre2}-0-course_type': 'required', f'{pre2}-0-recommended': 'on'})
        self.assertEqual(r.status_code, 302, r.context['form'].errors if r.status_code == 200 else '')
        self.assertTrue(CurriculumCourse.objects.filter(curriculum_semester=cs, course=c1, recommended=True).exists())

    def enroll(self, student, **extra):
        data = {'student': student.pk, 'program': self.program.pk, 'status': 'active', 'started_on': '2026-09-07', **extra}
        return self.client.post('/setup/enrollments/add/', data)

    def test_enrollment_second_active_for_same_student_is_rejected_with_a_clear_message(self):
        # Creating a student already gives them an active enrollment.
        self.assertTrue(Enrollment.objects.filter(student=self.bob, status='active').exists())
        r = self.enroll(self.bob)
        self.assertEqual(r.status_code, 200)
        text = ' '.join(r.context['form'].non_field_errors())
        self.assertIn('already has an active enrollment', text)
        self.assertNotIn('Constraint', text)
        self.assertEqual(Enrollment.objects.filter(student=self.bob, status='active').count(), 1)

    def test_after_ending_the_old_enrollment_a_new_one_can_be_added_and_warns_without_curriculum(self):
        Enrollment.objects.filter(student=self.bob).update(status='completed')
        r = self.enroll(self.bob)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(any('No curriculum is set' in m for m in self.msgs(r)))
        self.client.get('/setup/enrollments/')          # consume the queued messages
        cur = Curriculum.objects.create(program=self.program, name='C', version='1')
        e = Enrollment.objects.get(student=self.bob, status='active')
        r = self.client.post(f'/setup/enrollments/{e.pk}/edit/', {'student': self.bob.pk, 'program': self.program.pk, 'curriculum': cur.pk,
                                                                 'status': 'active', 'started_on': '2026-09-07'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(any('No curriculum' in m for m in self.msgs(r)))

    def test_scheme_with_components_and_weight_warning(self):
        course = Course.objects.create(code='CS300', name='Algorithms', credits=3, program=self.program)
        pre = self.inline_prefix('/setup/schemes/add/')
        def post(weights):
            data = {'course': course.pk, 'name': 'S', 'version': 1, 'is_active': 'on', f'{pre}-TOTAL_FORMS': len(weights),
                    f'{pre}-INITIAL_FORMS': 0, f'{pre}-MIN_NUM_FORMS': 0, f'{pre}-MAX_NUM_FORMS': 1000}
            for i, w in enumerate(weights):
                data.update({f'{pre}-{i}-name': f'Part {i}', f'{pre}-{i}-component_type': 'quiz', f'{pre}-{i}-weight': w,
                             f'{pre}-{i}-max_marks': w, f'{pre}-{i}-order': i, f'{pre}-{i}-is_required': 'on'})
            return self.client.post('/setup/schemes/add/', data)
        r = post([30, 30])
        self.assertTrue(any('add up to 60' in m for m in self.msgs(r)))
        self.assertEqual(AssessmentScheme.objects.get(course=course).components.count(), 2)

    def test_timeslot_and_entry_pages_save(self):
        r = self.client.post('/setup/timeslots/add/', {'day': 'tue', 'start_time': '11:00', 'end_time': '12:00'})
        self.assertEqual(r.status_code, 302)
        from timetable.models import TimeSlot
        self.assertTrue(TimeSlot.objects.filter(day='tue', start_time=datetime.time(11)).exists())

    def test_every_create_and_edit_is_audited_with_old_and_new_values(self):
        self.client.post('/setup/sessions/add/', {'year': '2030-2031', 'start_date': '2030-09-01', 'end_date': '2031-08-31'})
        sess = AcademicSession.objects.get(year='2030-2031')
        self.assertTrue(AuditLog.objects.filter(action='SETUP_CREATE').exists())
        self.client.post(f'/setup/sessions/{sess.pk}/edit/', {'year': '2030-2031', 'start_date': '2030-09-02', 'end_date': '2031-08-31'})
        log = AuditLog.objects.filter(action='SETUP_EDIT').latest('id')
        self.assertEqual(log.changes['start_date'], ['2030-09-01', '2030-09-02'])
        self.assertEqual(log.actor, self.root)

    def test_no_delete_route_exists(self):
        self.assertEqual(self.client.post('/setup/sessions/1/delete/', {}).status_code, 404)


class LoginAndRoleTests(SetupBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.root)

    def add(self, **kw):
        data = {'username': 'new.person', 'first_name': 'New', 'last_name': 'Person', 'email': 'n@x.com', 'role': 'faculty',
                'password': 'S0me-Strong-Pw!'}
        data.update(kw)
        return self.client.post('/setup/logins/add/', data)

    def test_create_login_sets_role_and_password(self):
        self.assertEqual(self.add().status_code, 302)
        u = User.objects.get(username='new.person')
        self.assertEqual(u.profile.role, 'faculty'); self.assertTrue(u.check_password('S0me-Strong-Pw!'))
        self.assertTrue(AuditLog.objects.filter(action='USER_CREATED').exists())

    def test_blank_password_creates_a_disabled_account(self):
        self.add(password='')
        self.assertFalse(User.objects.get(username='new.person').has_usable_password())

    def test_weak_or_duplicate_inputs_rejected(self):
        self.assertEqual(self.add(password='12345678').status_code, 200)          # too common/numeric
        self.assertFalse(User.objects.filter(username='new.person').exists())
        self.add(); self.assertEqual(self.add().status_code, 200)                  # duplicate username

    def test_admin_role_is_not_offered_or_accepted(self):
        self.assertEqual(self.add(role='admin').status_code, 200)
        self.assertFalse(User.objects.filter(username='new.person').exists())

    def test_change_role_but_never_an_administrator(self):
        self.client.post(f'/setup/logins/{self.bob.user.pk}/role/', {'role': 'guardian'})
        self.assertEqual(Profile.objects.get(user=self.bob.user).role, 'guardian')
        self.assertTrue(AuditLog.objects.filter(action='ROLE_CHANGED').exists())
        self.assertEqual(self.client.post(f'/setup/logins/{self.root.pk}/role/', {'role': 'student'}).status_code, 403)

    def test_only_security_permission_holders_can_manage_logins(self):
        for who in (self.alice.user, self.t1.user, self.operator('nosec', [('students', 'create')])):
            self.client.force_login(who)
            self.assertEqual(self.client.get('/setup/logins/').status_code, 403)
            self.assertEqual(self.client.post('/setup/logins/add/', {'username': 'x'}).status_code, 403)
        self.client.force_login(self.operator('sec', [('security', 'view'), ('security', 'create')]))
        self.assertEqual(self.client.get('/setup/logins/').status_code, 200)


class StaffRoleSignalTests(SetupBase):
    def test_new_staff_record_fixes_the_default_student_role(self):
        u = User.objects.create_user('lect1', password='pw')
        self.assertEqual(u.profile.role, 'student')
        Staff.objects.create(user=u, employee_id='E9', department=self.dept, role='lecturer')
        self.assertEqual(Profile.objects.get(user=u).role, 'faculty')
        u2 = User.objects.create_user('acct1', password='pw')
        Staff.objects.create(user=u2, employee_id='E10', department=self.dept, role='librarian')
        self.assertEqual(Profile.objects.get(user=u2).role, 'staff')

    def test_an_existing_non_default_role_is_never_overwritten(self):
        u = User.objects.create_user('guard1', password='pw'); Profile.objects.filter(user=u).update(role='guardian')
        Staff.objects.create(user=u, employee_id='E11', department=self.dept, role='lecturer')
        self.assertEqual(Profile.objects.get(user=u).role, 'guardian')


class LoginCreatingFormsTests(SetupBase):
    def test_teacher_form_creates_login_and_faculty_role_in_one_step(self):
        self.client.force_login(self.root)
        r = self.client.post('/hr/teachers/add/', {'new_username': 'dr.new', 'new_password': 'S0me-Strong-Pw!', 'new_first_name': 'Dr',
                                                   'new_last_name': 'New', 'employee_id': 'E20', 'department': self.dept.pk, 'role': 'professor'})
        self.assertEqual(r.status_code, 302, r.context['form'].errors if r.status_code == 200 else '')
        s = Staff.objects.get(employee_id='E20')
        self.assertEqual(s.user.username, 'dr.new'); self.assertEqual(s.user.profile.role, 'faculty')
        self.assertTrue(s.user.check_password('S0me-Strong-Pw!'))

    def test_office_job_gets_staff_role(self):
        self.client.force_login(self.root)
        self.client.post('/hr/teachers/add/', {'new_username': 'lib.new', 'new_password': 'S0me-Strong-Pw!', 'employee_id': 'E21',
                                               'department': self.dept.pk, 'role': 'librarian'})
        self.assertEqual(User.objects.get(username='lib.new').profile.role, 'staff')

    def test_teacher_form_requires_a_login_one_way_or_the_other(self):
        self.client.force_login(self.root)
        n = Staff.objects.count()
        r = self.client.post('/hr/teachers/add/', {'employee_id': 'E22', 'department': self.dept.pk, 'role': 'lecturer'})
        self.assertEqual(r.status_code, 200); self.assertEqual(Staff.objects.count(), n)
        r = self.client.post('/hr/teachers/add/', {'user': self.bob.user.pk, 'new_username': 'both', 'employee_id': 'E23', 'role': 'lecturer'})
        self.assertEqual(r.status_code, 200); self.assertEqual(Staff.objects.count(), n)

    def test_teacher_form_still_accepts_an_existing_login(self):
        self.client.force_login(self.root)
        u = User.objects.create_user('exist.t', password='pw')
        self.client.post('/hr/teachers/add/', {'user': u.pk, 'employee_id': 'E24', 'role': 'lecturer', 'department': self.dept.pk})
        self.assertEqual(Profile.objects.get(user=u).role, 'faculty')

    def student_data(self, **kw):
        d = {'new_username': 'new.student', 'full_name': 'New Student', 'admission_no': '2026-NEW-001', 'cnic': '40000-0009999-9',
             'status': 'active', 'program': self.program.pk}
        d.update(kw); return d

    def test_student_form_creates_a_disabled_login_when_no_password_given(self):
        self.client.force_login(self.root)
        r = self.client.post('/registration/students/add/', self.student_data())
        self.assertEqual(r.status_code, 302, r.context['form'].errors if r.status_code == 200 else '')
        u = User.objects.get(username='new.student')
        self.assertEqual(u.profile.role, 'student'); self.assertFalse(u.has_usable_password())
        self.assertEqual(Student.objects.get(admission_no='2026-NEW-001').user, u)

    def test_student_form_with_password_and_duplicate_username(self):
        self.client.force_login(self.root)
        self.client.post('/registration/students/add/', self.student_data(new_password='S0me-Strong-Pw!'))
        self.assertTrue(User.objects.get(username='new.student').check_password('S0me-Strong-Pw!'))
        r = self.client.post('/registration/students/add/', self.student_data(admission_no='2026-NEW-002'))
        self.assertEqual(r.status_code, 200)       # username already taken
        self.assertFalse(Student.objects.filter(admission_no='2026-NEW-002').exists())

    def test_a_data_entry_operator_with_students_permission_can_now_add_students(self):
        op = self.operator('dataentry', [('students', 'create'), ('students', 'edit')])
        self.client.force_login(op)
        self.assertEqual(self.client.post('/registration/students/add/', self.student_data()).status_code, 302)
        s = Student.objects.get(admission_no='2026-NEW-001')
        self.assertEqual(self.client.get(f'/registration/students/{s.pk}/edit/').status_code, 200)
        self.assertEqual(self.client.post('/hr/teachers/add/', {}).status_code, 403)        # no hr permission

    def test_teachers_and_students_still_cannot_add_students_or_teachers(self):
        for who in (self.t1.user, self.alice.user):
            self.client.force_login(who)
            self.assertEqual(self.client.get('/registration/students/add/').status_code, 403)
            self.assertEqual(self.client.get('/hr/teachers/add/').status_code, 403)


class StaffRegistrationAndHubTests(SetupBase):
    def test_staff_registration_goes_through_the_eligibility_service(self):
        self.client.force_login(self.root)
        with mock.patch('core.services.academic.AcademicEligibilityService.register_course',
                        side_effect=ValueError('Section is full. Prerequisite CS-101 not passed.')) as m:
            r = self.client.post('/setup/registrations/add/', {'student': self.carl.pk, 'section': self.sec1.pk})
        m.assert_called_once()
        self.assertContains(r, 'Section is full'); self.assertEqual(r.status_code, 200)
        reg = CourseRegistration.objects.get(student=self.alice, section=self.sec1)
        with mock.patch('core.services.academic.AcademicEligibilityService.register_course', return_value=reg):
            r = self.client.post('/setup/registrations/add/', {'student': self.alice.pk, 'section': self.sec1.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action='REGISTRATION_CREATED').exists())

    def test_registration_needs_permission(self):
        for who in (self.t1.user, self.alice.user, self.operator('noreg', [('students', 'create')])):
            self.client.force_login(who)
            self.assertEqual(self.client.get('/setup/registrations/add/').status_code, 403)

    def test_hub_reports_real_warnings(self):
        self.client.force_login(self.root)
        r = self.client.get('/setup/')
        text = r.content.decode()
        self.assertIn('have no curriculum', text)                    # fixture enrollments were created without one
        self.assertIn('have no instructor', text) if self.sec1.instructor is None else None
        self.assertGreaterEqual(r.context['total'], 20)
        self.assertEqual({s['n'] for s in r.context['steps']}, set(range(1, r.context['total'] + 1)))

    def test_hub_flags_staff_whose_login_is_still_a_student(self):
        u = User.objects.create_user('oldstaff', password='pw')
        Staff.objects.bulk_create([Staff(user=u, employee_id='E99', role='lecturer')])      # bypasses the signal on purpose
        self.client.force_login(self.root)
        self.assertContains(self.client.get('/setup/'), 'still have the Student role')

    def test_hub_visible_to_a_role_holder_but_links_follow_permissions(self):
        op = self.operator('hubop', [('curriculum', 'create')])
        self.client.force_login(op)
        r = self.client.get('/setup/')
        self.assertEqual(r.status_code, 200)
        by = {s['title']: s['allowed'] for s in r.context['steps']}
        self.assertTrue(by['Curriculum']); self.assertFalse(by['Students'])


class StaffFlagIsNotAdminTests(SetupBase):
    """Root-cause fix: a login with only the is_staff flag must never act as an administrator."""

    def test_user_role_only_calls_superusers_admin(self):
        from core.permissions import user_role
        plain = User.objects.create_user('flagged', password='pw', is_staff=True)
        self.assertEqual(plain.profile.role, 'staff')                   # the signal no longer grants 'admin'
        Profile.objects.filter(user=plain).update(role='admin')          # even a stale 'admin' profile role
        plain = User.objects.get(pk=plain.pk)
        self.assertEqual(user_role(plain), 'staff')
        self.assertEqual(user_role(self.root), 'admin')

    def test_flagged_staff_is_refused_on_admin_only_screens(self):
        plain = User.objects.create_user('flagged2', password='pw', is_staff=True)
        Profile.objects.filter(user=plain).update(role='admin')
        for url in ('/hr/payroll/', '/hr/teachers/add/', '/registration/students/add/', '/setup/'):
            self.client.force_login(plain)
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/hr/payroll/').status_code, 200)

    def test_a_governance_role_still_grants_exactly_what_it_says(self):
        op = self.operator('payonly', [('hr', 'view')])
        self.client.force_login(op)
        self.assertEqual(self.client.get('/hr/payroll/').status_code, 200)
        self.assertEqual(self.client.get('/hr/teachers/add/').status_code, 403)


class PaperApplicationTests(SetupBase):
    def test_staff_can_enter_a_paper_application_and_is_pointed_to_the_choices_screen(self):
        from admissions.models import Application
        op = self.operator('admdata', [('admissions', 'view'), ('admissions', 'create')])
        self.client.force_login(op)
        r = self.client.post('/setup/applications/add/', {'program': self.program.pk, 'full_name': 'Danish Warraich',
                                                         'email': 'danish.w@example.com', 'phone': '0300-0000011',
                                                         'admission_type': 'open_merit', 'district': 'Gujranwala', 'province': 'punjab',
                                                         'previous_percentage': '82.50'})
        self.assertEqual(r.status_code, 302)
        app = Application.objects.get(full_name='Danish Warraich')
        self.assertEqual((app.status, app.applicant, app.previous_percentage), ('pending', None, Decimal('82.50')))
        self.assertTrue(any(f'/admissions/applications/{app.pk}/preferences/' in m for m in self.msgs(r)))

    def test_status_cannot_be_set_from_this_screen_and_other_roles_are_refused(self):
        self.client.force_login(self.root)
        self.assertNotIn('status', self.client.get('/setup/applications/add/').context['form'].fields)
        for who in (self.t1.user, self.alice.user, self.operator('fin3', [('finance', 'create')])):
            self.client.force_login(who)
            self.assertEqual(self.client.get('/setup/applications/add/').status_code, 403)
