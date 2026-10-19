from django import forms
from django.contrib import admin, messages
from .models import Faculty, Department, Program, AcademicSession, Semester, Course, CourseSection, CourseRegistration, Curriculum, CurriculumSemester, CurriculumCourse
admin.site.register([Faculty, Department, Program, AcademicSession, Course, CourseSection, Curriculum, CurriculumSemester, CurriculumCourse])


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ('name', 'session', 'start_date', 'end_date', 'registration_open', 'registration_close', 'drop_deadline')
    list_filter = ('session',)
    fieldsets = (
        ('Semester', {'fields': ('name', 'session', 'semester_number', 'start_date', 'end_date')}),
        ('Course selection window', {
            'fields': ('registration_open', 'registration_close', 'drop_deadline'),
            'description': 'Students can register between "registration open" and "registration close", and can drop until the drop deadline. '
                           'If the drop deadline is blank it follows the registration close; if that is blank too, the default drop window in Site Settings applies.',
        }),
        ('Exam registration window', {
            'fields': ('exam_registration_open', 'exam_registration_close'),
            'description': 'Retake / improvement exam applications are only accepted inside this window. Leave both blank to not restrict.',
        }),
    )


class CourseRegistrationAdminForm(forms.ModelForm):
    """Validates eligibility in clean() - the correct place for
    cross-field admin validation, so a rejected registration shows a
    normal inline form error instead of a raw 500. save_model() (below)
    then creates it through the real service, which re-checks atomically
    at save time - clean() here is the friendly-error path, register_course()
    is the actual source of truth."""
    class Meta:
        model = CourseRegistration
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            return cleaned  # editing an existing registration - not a new-registration eligibility check
        student, section, semester = cleaned.get('student'), cleaned.get('section'), cleaned.get('semester')
        if student and section:
            from core.services.academic import AcademicEligibilityService
            result = AcademicEligibilityService.registration_eligibility(student, section, semester)
            if not result.eligible:
                raise forms.ValidationError('Could not register: ' + ' '.join(result.reasons))
        return cleaned


@admin.register(CourseRegistration)
class CourseRegistrationAdmin(admin.ModelAdmin):
    """Admin exposure for course registrations - deliberately routes new
    registrations through AcademicEligibilityService.register_course()
    instead of a raw save, so an admin creating one here is still subject
    to the same prerequisite/credit-limit/capacity/schedule-conflict/
    duplicate checks a student registering themselves would be. Only
    status changes (e.g. marking one dropped) save directly, since that's
    not the "create a new registration" action the eligibility check
    guards."""
    form = CourseRegistrationAdminForm
    list_display = ('student', 'course_code', 'section', 'semester', 'status', 'registered_at')
    list_filter = ('status', 'semester', 'section__course')
    search_fields = ('student__full_name', 'student__admission_no', 'section__course__code', 'section__course__name')
    readonly_fields = ('registered_at',)

    @admin.display(description='Course', ordering='section__course__code')
    def course_code(self, obj):
        return obj.section.course.code

    def save_model(self, request, obj, form, change):
        if change:
            # Editing an existing registration (e.g. status -> dropped) -
            # not a new-registration action, so no eligibility re-check.
            super().save_model(request, obj, form, change)
            return
        from core.services.academic import AcademicEligibilityService
        try:
            registration = AcademicEligibilityService.register_course(obj.student, obj.section_id, obj.semester)
        except ValueError as exc:
            # clean() already validated this above, so this should only
            # trigger on a genuine race (e.g. a seat taken between form
            # display and submit) - still handled without a 500.
            messages.error(request, f'Could not register: {exc}')
            return
        obj.pk = registration.pk