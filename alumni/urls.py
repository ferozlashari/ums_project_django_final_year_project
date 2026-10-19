from django.urls import path
from . import views

urlpatterns = [
    path('', views.directory, name='alumni-directory'),
    path('my-profile/', views.my_profile, name='alumni-my-profile'),
    path('<int:pk>/request-mentorship/', views.request_mentorship, name='alumni-request-mentorship'),
    path('mentorship/requests/', views.my_mentorship_requests, name='my-mentorship-requests'),
    path('mentorship/<int:pk>/respond/', views.respond_mentorship, name='respond-mentorship'),
    path('manage/', views.admin_alumni_list, name='admin-alumni-list'),
]
