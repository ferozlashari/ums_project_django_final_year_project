from django.contrib import admin
from .models import OnlineClass


@admin.register(OnlineClass)
class OnlineClassAdmin(admin.ModelAdmin):
    list_display = ('title', 'section', 'host', 'scheduled_at', 'status')
    list_filter = ('status',)
    readonly_fields = ('room_code',)
