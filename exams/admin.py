from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from .models import ExamSession, GradeEntry, RetakeApplication

admin.site.register(ExamSession)


@admin.register(GradeEntry)
class GradeEntryAdmin(admin.ModelAdmin):
    list_display = ('student', 'exam', 'marks', 'grade', 'attempt_type', 'entered_at', 'is_locked_display', 'admin_unlocked')
    list_filter = ('attempt_type', 'admin_unlocked')
    search_fields = ('student__full_name', 'student__admission_no', 'exam__name', 'exam__course__code')
    list_editable = ('admin_unlocked',)

    @admin.display(description='Locked?', boolean=True)
    def is_locked_display(self, obj):
        return obj.is_locked

    def save_model(self, request, obj, form, change):
        """Django admin bypassed the marks-lock rule entirely and never
        wrote to the audit trail - both real gaps, since this is one of
        the two places (along with the grade_edit view) marks can actually
        be changed. Fixed to enforce the same lock here, and to log every
        change the same way the rest of the app does."""
        from core.models import log_action

        tracked_fields = ['marks', 'grade', 'attempt_type', 'attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks']
        old = None
        if change:
            old = GradeEntry.objects.get(pk=obj.pk)
            if old.is_locked and not obj.admin_unlocked:
                messages.error(
                    request,
                    f"{old.student} / {old.exam} is locked (entered {old.entered_at:%d %b %Y}). "
                    "Tick 'Admin unlocked' to make an authorized override, or use Request Correction instead.",
                )
                raise PermissionDenied("This grade entry is locked. Set admin_unlocked to override.")

        super().save_model(request, obj, form, change)

        if change and old is not None:
            changes = {
                f: [str(getattr(old, f)), str(getattr(obj, f))]
                for f in tracked_fields if getattr(old, f) != getattr(obj, f)
            }
            if changes:
                log_action(
                    request.user, 'GRADE_UPDATED', obj=f'{obj.student} / {obj.exam}',
                    changes=changes, reason='Edited via Django admin.', request=request,
                )
        elif not change:
            log_action(
                request.user, 'GRADE_CREATED', obj=f'{obj.student} / {obj.exam}',
                changes={'marks': ['', str(obj.marks)]}, reason='Created via Django admin.', request=request,
            )


@admin.register(RetakeApplication)
class RetakeApplicationAdmin(admin.ModelAdmin):
    list_display = ('student', 'grade_entry', 'application_type', 'status', 'applied_at')
    list_filter = ('application_type', 'status')
    list_editable = ('status',)

from .models import AssessmentScheme, AssessmentComponent, AssessmentMark, ResultPublication
admin.site.register([AssessmentScheme, AssessmentComponent, AssessmentMark, ResultPublication])
