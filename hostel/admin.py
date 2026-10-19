from django.contrib import admin
from .models import Room, HostelApplication, Hostel


@admin.register(Hostel)
class HostelAdmin(admin.ModelAdmin):
    list_display = ('name', 'gender', 'warden_name', 'is_active', 'total_capacity', 'total_occupied')
    list_filter = ('gender', 'is_active')


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('hostel', 'block', 'number', 'room_type', 'capacity', 'occupied_count')
    list_filter = ('hostel', 'block', 'room_type')


@admin.register(HostelApplication)
class HostelApplicationAdmin(admin.ModelAdmin):
    list_display = ('student', 'room_type_preference', 'assigned_room', 'status', 'applied_at')
    list_filter = ('status', 'room_type_preference')
    list_editable = ('status',)
