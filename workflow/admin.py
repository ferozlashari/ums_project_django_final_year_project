from django.contrib import admin
from .models import WorkflowRequest


@admin.register(WorkflowRequest)
class WorkflowRequestAdmin(admin.ModelAdmin):
    list_display = ('request_type', 'requested_by', 'subject', 'status', 'decided_by', 'created_at')
    list_filter = ('request_type', 'status')
    readonly_fields = ('requested_by', 'created_at', 'decided_by', 'decided_at')
