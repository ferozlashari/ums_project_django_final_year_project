from django.contrib import admin
from .models import Profile, Campus, Notice, SiteSettings, Notification, SMSOutboxMessage, AuditLog

admin.site.register(Profile)
admin.site.register(Campus)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only by design - an audit trail that could be edited or
    deleted through the same admin it's supposed to be watching isn't a
    trustworthy audit trail. No add/change/delete permission for anyone,
    superuser included; entries are only ever created by log_action()."""
    list_display = ('created_at', 'actor', 'action', 'object_repr', 'ip_address')
    list_filter = ('action',)
    search_fields = ('object_repr', 'actor__username', 'reason')
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SMSOutboxMessage)
class SMSOutboxMessageAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'user', 'message', 'sent', 'created_at')
    list_filter = ('sent',)
    search_fields = ('phone_number', 'user__username', 'message')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'level', 'is_read', 'created_at')
    list_filter = ('level', 'is_read')
    search_fields = ('title', 'message', 'user__username')


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ('title', 'posted_by', 'published_at')
    search_fields = ('title', 'body')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'maintenance_mode', 'updated_at')

    def has_add_permission(self, request):
        # Singleton - only one row should ever exist.
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

from .models import AutomationRun, AutomationTask, ExceptionRecord, DataQualityIssue
admin.site.register([AutomationRun, AutomationTask, ExceptionRecord, DataQualityIssue])
