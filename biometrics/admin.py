from django.contrib import admin
from .models import BiometricProviderConfig, BiometricVerificationEvent, ExamAttendance, OnlineClassAttendance

admin.site.register(ExamAttendance)
admin.site.register(OnlineClassAttendance)


@admin.register(BiometricProviderConfig)
class BiometricProviderConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider_type', 'device_identifier', 'campus', 'is_enabled', 'last_seen_at')
    list_filter = ('provider_type', 'is_enabled', 'campus')
    search_fields = ('name', 'device_identifier')


@admin.register(BiometricVerificationEvent)
class BiometricVerificationEventAdmin(admin.ModelAdmin):
    list_display = ('student', 'provider', 'result', 'captured_at', 'section')
    list_filter = ('result', 'provider')
    date_hierarchy = 'captured_at'
    readonly_fields = [f.name for f in BiometricVerificationEvent._meta.fields]

    def has_add_permission(self, request):
        return False  # events are created only by real verification attempts, never typed in by hand
