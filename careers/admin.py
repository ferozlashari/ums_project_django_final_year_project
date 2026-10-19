from django.contrib import admin
from .models import Employer, JobPosting, JobApplication, ResumeProfile

admin.site.register(Employer)
admin.site.register(ResumeProfile)


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ('title', 'employer', 'posting_type', 'is_active', 'posted_at')
    list_filter = ('posting_type', 'is_active')
    search_fields = ('title', 'employer__name')


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('student', 'posting', 'status', 'applied_at')
    list_filter = ('status',)
