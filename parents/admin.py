from django.contrib import admin
from .models import GuardianLink


@admin.register(GuardianLink)
class GuardianLinkAdmin(admin.ModelAdmin):
    list_display = ('guardian', 'student', 'relation', 'is_verified', 'requested_at')
    list_filter = ('is_verified', 'relation')
    search_fields = ('guardian__username', 'student__full_name', 'student__admission_no')
