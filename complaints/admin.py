from django.contrib import admin
from .models import Complaint


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ('subject', 'user', 'category', 'status', 'created_at')
    list_filter = ('category', 'status')
    search_fields = ('subject', 'description', 'user__username')
    list_editable = ('status',)
