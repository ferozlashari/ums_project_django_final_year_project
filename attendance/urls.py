from django.urls import path
from . import views

urlpatterns = [
    path('', views.attendance_list, name='attendance-list'),
    path('add/', views.attendance_add, name='attendance-add'),
    path('corrections/', views.corrections_queue, name='attendance-corrections'),
    path('corrections/request/<int:session_id>/', views.correction_request, name='attendance-correction-request'),
    path('bulk/', views.bulk_attendance, name='bulk-attendance'),
    path('check-in/', views.self_checkin, name='attendance-checkin'),
    path('check-out/', views.self_checkout, name='attendance-checkout'),
    path('biometric-check-in/', views.biometric_checkin, name='attendance-biometric-checkin'),
    path('device-check-in/<str:provider_type>/', views.physical_biometric_checkin, name='attendance-device-checkin'),
]
