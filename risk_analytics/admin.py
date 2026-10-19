from django.contrib import admin
from .models import RiskFlag


@admin.register(RiskFlag)
class RiskFlagAdmin(admin.ModelAdmin):
    list_display = ('student', 'level', 'attendance_pct', 'average_percentage', 'is_resolved', 'last_computed_at')
    list_filter = ('level', 'is_resolved')
    search_fields = ('student__full_name',)
