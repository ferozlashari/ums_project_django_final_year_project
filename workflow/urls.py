from django.urls import path
from . import views

urlpatterns = [
    path("request/", views.submit_request, name="submit-workflow-request"),
    path("mine/", views.my_requests, name="my-workflow-requests"),
    path("center/", views.workflow_center, name="workflow-center"),
    path("<int:pk>/approve/", views.approve_request, name="workflow-approve"),
    path("<int:pk>/reject/", views.reject_request, name="workflow-reject"),
]
