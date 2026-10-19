from django.contrib import admin
from .models import Scholarship, ScholarshipApplication


@admin.register(Scholarship)
class ScholarshipAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'application_deadline', 'active')
    list_filter = ('active',)


@admin.register(ScholarshipApplication)
class ScholarshipApplicationAdmin(admin.ModelAdmin):
    list_display = ('student', 'scholarship', 'status', 'applied_at')
    list_filter = ('status',)
    list_editable = ('status',)
