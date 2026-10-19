from django.urls import path
from . import views

urlpatterns = [
    path('courses/', views.course_list, name='course-list'),
    path('courses/add/', views.course_add, name='course-add'),
    path('courses/<int:pk>/edit/', views.course_edit, name='course-edit'),
    path('departments/', views.department_list, name='department-list'),
    path('departments/add/', views.department_add, name='department-add'),
    path('departments/<int:pk>/edit/', views.department_edit, name='department-edit'),
    path('faculties/', views.faculty_list, name='faculty-list'),
    path('faculties/add/', views.faculty_add, name='faculty-add'),
    path('faculties/<int:pk>/edit/', views.faculty_edit, name='faculty-edit'),
    path('programs/', views.program_list, name='program-list'),
    path('programs/add/', views.program_add, name='program-add'),
    path('programs/<int:pk>/edit/', views.program_edit, name='program-edit'),
    path('section-management/', views.section_list, name='section-list'),
    path('section-management/add/', views.section_add, name='section-add'),
    path('section-management/<int:pk>/edit/', views.section_edit, name='section-edit'),
    path('sections/', views.browse_sections, name='browse-sections'),
    path('sections/<int:section_id>/register/', views.register_section, name='register-section'),
    path('my-registrations/', views.my_registrations, name='my-registrations'),
    path('my-registrations/<int:pk>/drop/', views.drop_registration, name='drop-registration'),
]
