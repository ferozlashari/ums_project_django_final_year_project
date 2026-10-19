from django.contrib import admin
from .models import Application, EntryTest


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'email', 'phone', 'program', 'status', 'applied_at')
    list_filter = ('status', 'program')
    search_fields = ('full_name', 'email', 'phone', 'applicant__username')
    list_editable = ('status',)


@admin.register(EntryTest)
class EntryTestAdmin(admin.ModelAdmin):
    list_display = ('roll_number', 'application', 'test_date', 'marks_obtained')
    search_fields = ('roll_number',)
