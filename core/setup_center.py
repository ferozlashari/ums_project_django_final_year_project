"""Data Entry Hub - app screens for everything an administrator needs, without the Django admin.

Each record type below gets list / add / edit screens at /setup/<key>/ that are
  * gated by a governance permission (module + action) - Super Admin always passes, a plain
    is_staff flag never does;
  * audited (who created or changed what, with old and new values);
  * delete-free on purpose: records are edited or deactivated, never deleted, because results,
    fees and attendance depend on their history.
The hub page (/setup/) lists the entry steps in dependency order with live counts and warnings.
"""
from collections import OrderedDict

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import inlineformset_factory, modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from governance.permissions import has_perm


def _models():
    from academics.models import (AcademicSession, Curriculum, CurriculumCourse, CurriculumSemester, Semester)
    from admissions.models import Application, EntryTest
    from exams.models import AssessmentComponent, AssessmentScheme
    from finance.models import FeeItem, FeePolicy
    from registration.models import Enrollment
    from timetable.models import TimeSlot
    return locals()


def registry():
    m = _models()
    return OrderedDict([
        ('sessions', dict(model=m['AcademicSession'], module='programs', title='Academic Sessions',
                          cols=['year', 'start_date', 'end_date'],
                          fields=['year', 'start_date', 'end_date'])),
        ('semesters', dict(model=m['Semester'], module='programs', title='Semesters',
                           cols=['name', 'session', 'start_date', 'end_date', 'registration_open', 'registration_close'],
                           fields=['name', 'session', 'semester_number', 'start_date', 'end_date', 'registration_open',
                                   'registration_close', 'drop_deadline', 'exam_registration_open', 'exam_registration_close'],
                           help='Exactly one semester should cover today\'s date. Registration and drop dates take a date AND time.')),
        ('curricula', dict(model=m['Curriculum'], module='curriculum', title='Curricula',
                           cols=['name', 'program', 'version', 'total_credits', 'is_active'],
                           fields=['program', 'name', 'version', 'effective_from', 'effective_to', 'total_credits', 'is_active'],
                           inline=dict(model=m['CurriculumSemester'], fields=['semester_number', 'title', 'credits_required'],
                                       extra=2, label='Curriculum semesters (one row per semester of the plan)'),
                           help='Add the semesters here; then open "Curriculum semesters" to attach courses to each.')),
        ('curriculum-semesters', dict(model=m['CurriculumSemester'], module='curriculum', title='Curriculum semesters and their courses',
                                      cols=['curriculum', 'semester_number', 'title', 'credits_required'],
                                      fields=['curriculum', 'semester_number', 'title', 'credits_required'],
                                      inline=dict(model=m['CurriculumCourse'],
                                                  fields=['course', 'course_type', 'elective_group', 'recommended', 'minimum_grade'],
                                                  extra=5, label='Courses in this semester'),
                                      help='Courses marked Recommended are offered automatically to students in this semester.')),
        ('enrollments', dict(model=m['Enrollment'], module='students', title='Enrollments',
                             cols=['student', 'program', 'curriculum', 'status', 'started_on'],
                             fields=['student', 'program', 'curriculum', 'status', 'started_on', 'ended_on'],
                             help='Always set the Curriculum: without it course recommendations and progress cannot work. A student can have only one active enrollment.')),
        ('timeslots', dict(model=m['TimeSlot'], module='sections', title='Time slots',
                           cols=['day', 'start_time', 'end_time'], fields=['day', 'start_time', 'end_time'])),
        ('schemes', dict(model=m['AssessmentScheme'], module='grade_policy', title='Assessment schemes',
                         cols=['course', 'name', 'version', 'is_active'],
                         fields=['course', 'name', 'version', 'is_active'],
                         inline=dict(model=m['AssessmentComponent'],
                                     fields=['name', 'component_type', 'weight', 'max_marks', 'order', 'is_required'],
                                     extra=5, label='Components (weights should add up to 100)'),
                         help='Once a course has an active scheme its teacher enters marks on the marks sheet. If you add a new version, untick Is active on the old one.')),
        ('fee-policies', dict(model=m['FeePolicy'], module='finance', title='Fee policies (extra fees only)',
                              cols=['name', 'program', 'semester', 'version', 'is_active'],
                              fields=['name', 'program', 'semester', 'version', 'is_active', 'late_fee_per_day'],
                              inline=dict(model=m['FeeItem'], fields=['code', 'name', 'amount', 'category'], extra=3, label='Fee items'),
                              help='The usual fees (application, admission, semester, degree) come from the Program. Never overwrite an old policy - add a new version.')),
        ('applications', dict(model=m['Application'], module='admissions', title='Admission applications (paper forms)',
                              cols=['full_name', 'program', 'admission_type', 'district', 'province', 'previous_percentage', 'status'],
                              fields=['program', 'full_name', 'email', 'phone', 'admission_type', 'district', 'province',
                                      'previous_percentage', 'remark'],
                              help='For forms handed in on paper. Online applicants apply themselves at /admissions/apply/. '
                                   'After saving, enter the applicant\'s program choices (choice 1 required, up to 5, no gaps or duplicates).')),
        ('entry-tests', dict(model=m['EntryTest'], module='admissions', title='Entry tests',
                             cols=['application', 'roll_number', 'test_date', 'test_time', 'venue', 'marks_obtained'],
                             fields=['application', 'roll_number', 'test_date', 'test_time', 'venue', 'marks_obtained'])),
    ])


# ---------------------------------------------------------------- helpers
def _widgets(model, fields):
    out = {}
    for name in fields:
        f = model._meta.get_field(name)
        t = f.get_internal_type()
        if t == 'DateField':
            out[name] = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
        elif t == 'DateTimeField':
            out[name] = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
        elif t == 'TimeField':
            out[name] = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
    return out


def _allowed(user, cfg, action):
    return has_perm(user, cfg['module'], action)


def _require(user, cfg, action):
    if not _allowed(user, cfg, action):
        raise PermissionDenied(f'You need the "{action}" permission on {cfg["module"]} for this screen.')


def _cell(obj, col):
    import datetime
    v = getattr(obj, col)
    if v is None or v == '':
        return '-'
    if isinstance(v, bool):
        return 'Yes' if v else 'No'
    if isinstance(v, datetime.datetime):
        return (timezone.localtime(v) if timezone.is_aware(v) else v).strftime('%Y-%m-%d %H:%M')
    if isinstance(v, datetime.date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, datetime.time):
        return v.strftime('%H:%M')
    return str(v)


def _audit(user, action, obj, changes=None, reason=''):
    from core.models import log_action
    log_action(user, action, obj=f'{obj._meta.verbose_name}: {obj}', changes=changes or {}, reason=reason)


# ---------------------------------------------------------------- generic screens
@login_required
def setup_list(request, key):
    cfg = registry().get(key) or _404()
    _require(request.user, cfg, 'view')
    rows = cfg['model'].objects.all().order_by('-pk')[:200]
    return render(request, 'core/setup-list.html', {
        'key': key, 'cfg': cfg, 'cols': [(c, c.replace('_', ' ').title()) for c in cfg['cols']],
        'rows': [{'obj': o, 'cells': [_cell(o, c) for c in cfg['cols']]} for o in rows],
        'can_add': _allowed(request.user, cfg, 'create'), 'can_edit': _allowed(request.user, cfg, 'edit'),
    })


def _404():
    from django.http import Http404
    raise Http404()


@login_required
def setup_form(request, key, pk=None):
    cfg = registry().get(key) or _404()
    _require(request.user, cfg, 'edit' if pk else 'create')
    model = cfg['model']
    instance = get_object_or_404(model, pk=pk) if pk else None
    Form = modelform_factory(model, fields=cfg['fields'], widgets=_widgets(model, cfg['fields']))
    FormSet = None
    if cfg.get('inline'):
        inl = cfg['inline']
        FormSet = inlineformset_factory(model, inl['model'], fields=inl['fields'], extra=inl['extra'], can_delete=False,
                                        widgets=_widgets(inl['model'], inl['fields']))
    if request.method == 'POST':
        form = Form(request.POST, instance=instance)
        formset = FormSet(request.POST, instance=instance) if FormSet else None
        _ok = form.is_valid()
        _friendly(form)
        if _ok and (formset is None or formset.is_valid()):
            with transaction.atomic():
                obj = form.save()
                if formset is not None:
                    formset.instance = obj
                    formset.save()
                if instance is None:
                    _audit(request.user, 'SETUP_CREATE', obj, {'created': ['', str(obj)]})
                else:
                    changes = {f: [str(form.initial.get(f, '')), str(form.cleaned_data.get(f, ''))] for f in form.changed_data}
                    _audit(request.user, 'SETUP_EDIT', obj, changes)
            _post_save_notes(request, key, obj)
            messages.success(request, f'{model._meta.verbose_name.title()} saved.')
            return redirect('setup-list', key=key)
    else:
        form = Form(instance=instance)
        formset = FormSet(instance=instance) if FormSet else None
    return render(request, 'core/setup-form.html', {
        'key': key, 'cfg': cfg, 'form': form, 'formset': formset, 'instance': instance,
        'inline_label': cfg.get('inline', {}).get('label', ''),
    })


FRIENDLY_ERRORS = {
    'uniq_one_active_enrollment_per_student':
        'This student already has an active enrollment. Edit that enrollment, or set its status to completed/withdrawn first.',
}


def _friendly(form):
    """Replace raw database-constraint messages with something a data-entry operator can act on."""
    errs = form._errors.get('__all__') if form._errors else None
    if errs:
        fixed = [next((v for k, v in FRIENDLY_ERRORS.items() if k in str(e)), str(e)) for e in errs]
        form._errors['__all__'] = form.error_class(fixed)


def _post_save_notes(request, key, obj):
    """Non-blocking advice after a save."""
    if key == 'schemes':
        total = sum(c.weight for c in obj.components.all())
        if total != 100:
            messages.warning(request, f'The component weights add up to {total}, not 100. Marks totals will not be out of 100.')
        elif not obj.is_active:
            messages.info(request, 'This scheme is not active, so teachers cannot use it yet.')
    if key == 'applications':
        from django.urls import reverse
        messages.info(request, f'Next: enter this applicant\'s program choices at {reverse("application-preferences", args=[obj.pk])}')
    if key == 'enrollments' and obj.curriculum_id is None:
        messages.warning(request, 'No curriculum is set - this student will get no recommended courses and no progress tracking.')


# ---------------------------------------------------------------- logins
class LoginForm(forms.Form):
    ROLES = [('faculty', 'Faculty (teacher)'), ('staff', 'Staff (office / officer)'), ('student', 'Student'),
             ('guardian', 'Parent / Guardian')]
    username = forms.CharField(max_length=150, help_text='Lower case, e.g. imran.shah. Must be unique.')
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False, help_text='Needed for verification and password-reset emails.')
    role = forms.ChoiceField(choices=ROLES)
    password = forms.CharField(widget=forms.PasswordInput, required=False, min_length=8,
                               help_text='8+ characters. Leave blank to create the account disabled (the person uses "Forgot password").')

    def clean_username(self):
        u = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('That username already exists.')
        return u


def _security_required(request, action):
    if not has_perm(request.user, 'security', action):
        raise PermissionDenied(f'You need the "{action}" permission on Security (users / roles).')


@login_required
def login_list(request):
    _security_required(request, 'view')
    users = User.objects.select_related('profile').order_by('-date_joined')[:200]
    return render(request, 'core/setup-logins.html', {
        'users': users, 'can_add': has_perm(request.user, 'security', 'create'),
        'can_edit': has_perm(request.user, 'security', 'edit')})


@login_required
def login_add(request):
    _security_required(request, 'create')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        from core.services.accounts import create_login
        from django.contrib.auth.password_validation import validate_password
        d = form.cleaned_data
        try:
            user = create_login(d['username'], d['password'], d['first_name'], d['last_name'], d['email'], d['role'])
        except forms.ValidationError as exc:
            form.add_error('password', exc)
        except Exception as exc:  # password validators raise django ValidationError subclasses
            form.add_error('password', getattr(exc, 'messages', [str(exc)]))
        else:
            from core.models import log_action
            log_action(request.user, 'USER_CREATED', obj=f'login: {user.username}', changes={'role': ['', d['role']]})
            messages.success(request, f'Login "{user.username}" created with role {d["role"]}.'
                                      + ('' if d['password'] else ' The account is disabled until a password is set.'))
            return redirect('setup-logins')
    return render(request, 'core/setup-form.html', {'key': 'logins', 'cfg': {'title': 'Create login'}, 'form': form, 'formset': None,
                                                    'instance': None, 'inline_label': '', 'plain': True,
                                                    'back': 'setup-logins'})


@login_required
def login_role(request, pk):
    """Change a person's profile role (e.g. a new teacher -> Faculty). Administrators are never changed here."""
    _security_required(request, 'edit')
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser:
        raise PermissionDenied('Administrator accounts cannot be changed here.')
    from core.models import Profile

    class RoleForm(forms.Form):
        role = forms.ChoiceField(choices=LoginForm.ROLES)

    current = getattr(getattr(user, 'profile', None), 'role', 'student')
    form = RoleForm(request.POST or None, initial={'role': current})
    if request.method == 'POST' and form.is_valid():
        from core.models import log_action
        from core.services.accounts import set_profile_role
        new = form.cleaned_data['role']
        set_profile_role(user, new)
        log_action(request.user, 'ROLE_CHANGED', obj=f'login: {user.username}', changes={'role': [current, new]})
        messages.success(request, f'{user.username} is now {new}.')
        return redirect('setup-logins')
    return render(request, 'core/setup-form.html', {'key': 'logins', 'cfg': {'title': f'Role for {user.username}'}, 'form': form,
                                                    'formset': None, 'instance': user, 'inline_label': '', 'plain': True,
                                                    'back': 'setup-logins'})


# ---------------------------------------------------------------- course registration by staff
class StaffRegistrationForm(forms.Form):
    student = forms.ModelChoiceField(queryset=None)
    section = forms.ModelChoiceField(queryset=None)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from academics.models import CourseSection
        from registration.models import Student
        self.fields['student'].queryset = Student.objects.filter(status='active').order_by('full_name')
        self.fields['section'].queryset = CourseSection.objects.select_related('course').order_by('course__code', 'code')


@login_required
def registration_add(request):
    """Register a student on their behalf - through the same eligibility rules as the student's own screen."""
    if not has_perm(request.user, 'registration', 'create'):
        raise PermissionDenied('You need the "create" permission on Course Registration.')
    from core.services.academic import AcademicEligibilityService as S
    form = StaffRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                reg = S.register_course(form.cleaned_data['student'], form.cleaned_data['section'].pk)
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            from core.models import log_action
            log_action(request.user, 'REGISTRATION_CREATED', obj=str(reg), changes={'by': ['', 'staff']})
            messages.success(request, f'Registered: {reg}.')
            return redirect('setup-registration-add')
    return render(request, 'core/setup-form.html', {
        'key': 'registrations', 'cfg': {'title': 'Register a student for a course',
                                        'help': 'Uses the same checks as the student\'s own screen: registration window, prerequisites, credit limit, seat capacity, timetable clashes and curriculum.'},
        'form': form, 'formset': None, 'instance': None, 'inline_label': '', 'plain': True, 'back': 'setup-hub'})


# ---------------------------------------------------------------- the hub
def _count(model, **kw):
    return model.objects.filter(**kw).count()


@login_required
def setup_hub(request):
    from academics.models import (AcademicSession, Course, CourseRegistration, CourseSection, Curriculum, Department,
                                  Faculty, Program, Semester)
    from admissions.models import Application
    from exams.models import AssessmentScheme, GradeScale
    from hr.models import Staff
    from registration.models import Enrollment, Student
    from timetable.models import Room, TimeSlot, TimetableAssignment
    from core.permissions import user_role
    from governance.permissions import _current_assignments
    u = request.user
    if not (user_role(u) == 'admin' or _current_assignments(u)):
        raise PermissionDenied('The Data Entry Hub is for administrators and staff with an assigned role.')
    today = timezone.localdate()

    def can(module, action='create'):
        return has_perm(u, module, action)

    def step(n, title, count, url, module, warn=None, note=''):
        return {'n': n, 'title': title, 'count': count, 'url': url, 'module': module,
                'allowed': can(module) or can(module, 'view'), 'warn': warn, 'note': note,
                'state': 'missing' if not count else ('warn' if warn else 'done')}

    no_fee = Program.objects.filter(semester_fee__lte=0).count()
    current_sem = Semester.objects.filter(start_date__lte=today, end_date__gte=today).count()
    steps = [
        step(1, 'Faculty', Faculty.objects.count(), '/academics/faculties/add/', 'programs'),
        step(2, 'Department', Department.objects.count(), '/academics/departments/add/', 'programs'),
        step(3, 'Program (with fees)', Program.objects.count(), '/academics/programs/add/', 'programs',
             warn=f'{no_fee} program(s) have no semester fee - challans will be wrong.' if no_fee else None),
        step(4, 'Academic session', AcademicSession.objects.count(), '/setup/sessions/', 'programs'),
        step(5, 'Semester (one must cover today)', Semester.objects.count(), '/setup/semesters/', 'programs',
             warn=None if current_sem == 1 else ('No semester covers today\'s date.' if current_sem == 0 else f'{current_sem} semesters cover today - there should be exactly one.')),
        step(6, 'Courses', Course.objects.count(), '/academics/courses/add/', 'courses'),
        step(7, 'Curriculum', Curriculum.objects.count(), '/setup/curricula/', 'curriculum',
             warn=f'{Curriculum.objects.filter(semesters__isnull=True).count()} curriculum(s) have no semesters.' if Curriculum.objects.filter(semesters__isnull=True).exists() else None),
        step(8, 'Curriculum courses (per semester)', _models()['CurriculumCourse'].objects.count(), '/setup/curriculum-semesters/', 'curriculum'),
        step(9, 'Grade scale', GradeScale.objects.count(), '/exams/grade-scale/', 'grade_policy'),
        step(10, 'Assessment schemes', AssessmentScheme.objects.count(), '/setup/schemes/', 'grade_policy',
             warn=f'{Course.objects.exclude(assessment_schemes__is_active=True).count()} course(s) have no active scheme (teachers cannot use the marks sheet for them).' if Course.objects.exists() and Course.objects.exclude(assessment_schemes__is_active=True).exists() else None),
        step(11, 'Rooms', Room.objects.count(), '/timetable/rooms/add/', 'sections'),
        step(12, 'Time slots', TimeSlot.objects.count(), '/setup/timeslots/', 'sections'),
        step(13, 'Logins and roles', User.objects.count(), '/setup/logins/', 'security',
             warn=f'{Staff.objects.filter(user__profile__role="student").count()} staff member(s) still have the Student role.' if Staff.objects.filter(user__profile__role='student').exists() else None),
        step(14, 'Teachers', Staff.objects.count(), '/hr/teachers/add/', 'hr'),
        step(15, 'Sections', CourseSection.objects.count(), '/academics/section-management/add/', 'sections',
             warn=f'{CourseSection.objects.filter(instructor__isnull=True).count()} section(s) have no instructor.' if CourseSection.objects.filter(instructor__isnull=True).exists() else None),
        step(16, 'Timetable', TimetableAssignment.objects.count(), '/timetable/add/', 'sections',
             warn=f'{TimetableAssignment.objects.filter(status="draft").count()} timetable row(s) are still Draft and will not show.' if TimetableAssignment.objects.filter(status='draft').exists() else None),
        step(17, 'Admission applications (paper forms)', Application.objects.count(), '/setup/applications/', 'admissions'),
        step(18, 'Entry tests', _models()['EntryTest'].objects.count(), '/setup/entry-tests/', 'admissions'),
        step(19, 'Students', Student.objects.count(), '/registration/students/add/', 'students'),
        step(20, 'Enrollments', Enrollment.objects.count(), '/setup/enrollments/', 'students',
             warn=f'{Student.objects.exclude(enrollments__status="active").count()} student(s) have no active enrollment.' if Student.objects.exclude(enrollments__status='active').exists() else
             (f'{Enrollment.objects.filter(status="active", curriculum__isnull=True).count()} active enrollment(s) have no curriculum.' if Enrollment.objects.filter(status='active', curriculum__isnull=True).exists() else None)),
        step(21, 'Course registrations', CourseRegistration.objects.count(), '/setup/registrations/add/', 'registration'),
    ]
    return render(request, 'core/setup-hub.html', {
        'steps': steps, 'done': sum(1 for s in steps if s['state'] == 'done'), 'total': len(steps),
        'warnings': [s for s in steps if s['warn']],
    })
