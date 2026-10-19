from django.urls import path
from . import views

urlpatterns = [
    path('students/', views.student_list, name='student-list'),
    path('students/add/', views.student_add, name='student-add'),
    path('students/<int:pk>/edit/', views.student_edit, name='student-edit'),
    path('students/<int:pk>/delete/', views.student_delete, name='student-delete'),
    path('students/import/', views.student_import, name='student-import'),
    path('students/export/', views.student_export, name='student-export'),
    path('students/<int:pk>/id-card/', views.id_card, name='id-card'),
    path('id-card/', views.id_card, name='my-id-card'),
]
