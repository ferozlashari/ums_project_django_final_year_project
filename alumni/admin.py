from django.contrib import admin
from .models import AlumniProfile, MentorshipRequest


@admin.register(AlumniProfile)
class AlumniProfileAdmin(admin.ModelAdmin):
    list_display = ('student', 'graduation_year', 'current_employer', 'willing_to_mentor', 'is_public')
    list_filter = ('graduation_year', 'willing_to_mentor', 'is_public')
    search_fields = ('student__full_name', 'current_employer', 'industry')


@admin.register(MentorshipRequest)
class MentorshipRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'alumni', 'status', 'created_at')
    list_filter = ('status',)
