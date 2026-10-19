from django.contrib import admin
from .models import Student, Enrollment


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'admission_no', 'program', 'gender', 'district', 'province', 'status')
    list_filter = ('program', 'gender', 'province', 'district', 'status')
    search_fields = ('full_name', 'admission_no', 'district')


admin.site.register(Enrollment)