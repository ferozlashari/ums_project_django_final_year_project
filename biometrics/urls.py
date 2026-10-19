from django.urls import path
from . import views

urlpatterns = [
    path('exams/<int:exam_id>/verify/', views.verify_exam_attendance, name='verify-exam-attendance'),
    path('classes/<int:pk>/verify-join/', views.verify_online_class_join, name='verify-online-class-join'),
    path('command-center/', views.command_center, name='biometric-command-center'),
]
