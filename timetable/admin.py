from django.contrib import admin
from .models import Room, TimeSlot, TimetableAssignment
admin.site.register(Room)
admin.site.register(TimeSlot)
admin.site.register(TimetableAssignment)