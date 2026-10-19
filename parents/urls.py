from django.urls import path
from . import views

urlpatterns = [
    path('', views.guardian_dashboard, name='guardian-dashboard'),
    path('link/', views.request_link, name='guardian-request-link'),
    path('manage-links/', views.manage_links, name='manage-guardian-links'),
    path('manage-links/<int:pk>/verify/', views.verify_link, name='verify-guardian-link'),
    path('manage-links/<int:pk>/reject/', views.reject_link, name='reject-guardian-link'),
]
