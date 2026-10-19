from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.retention_dashboard, name='retention-dashboard'),
    path('recalculate/', views.recalculate_now, name='recalculate-risk-flags'),
    path('<int:pk>/resolve/', views.resolve_flag, name='resolve-risk-flag'),
]
