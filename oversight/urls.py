from django.urls import path
from . import views

urlpatterns = [
    path("exceptions/", views.exception_center, name="exception-center"),
    path("data-quality/", views.data_quality_center, name="data-quality-center"),
]
