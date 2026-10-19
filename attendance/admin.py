from django.contrib import admin
from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'section', 'date', 'present', 'recorded_by')
    list_filter = ('present', 'date')
    search_fields = ('student__full_name',)
