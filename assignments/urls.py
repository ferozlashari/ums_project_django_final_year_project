from django.urls import path
from . import views

urlpatterns = [
    path('', views.assignment_list, name='assignment-list'),
    path('add/', views.assignment_add, name='assignment-add'),
    path('<int:pk>/submit/', views.submit_assignment, name='assignment-submit'),
    path('<int:pk>/submissions/', views.assignment_submissions, name='assignment-submissions'),
    path('submissions/<int:pk>/grade/', views.grade_submission, name='grade-submission'),
]
