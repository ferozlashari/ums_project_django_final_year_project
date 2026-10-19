from django.urls import path
from . import views

urlpatterns = [
    path('', views.my_complaints, name='my-complaints'),
    path('submit/', views.submit_complaint, name='submit-complaint'),
    path('manage/', views.manage_complaints, name='manage-complaints'),
    path('manage/<int:pk>/respond/', views.respond_complaint, name='respond-complaint'),
]
