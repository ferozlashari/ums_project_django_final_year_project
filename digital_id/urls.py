from django.urls import path
from . import views

urlpatterns = [
    path("verify/<str:token>/", views.verify_id, name="digital-id-verify"),
]
