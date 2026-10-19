from django.contrib import admin
from .models import Vehicle, Route, RouteStop, StudentTransportAssignment

admin.site.register(Vehicle)
admin.site.register(RouteStop)


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'vehicle', 'fare_per_semester', 'is_active')


@admin.register(StudentTransportAssignment)
class StudentTransportAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'route', 'stop', 'is_active')
    search_fields = ('student__full_name',)
