from django.urls import path
from . import views

urlpatterns = [
    path('', views.job_list, name='job-list'),
    path('<int:pk>/apply/', views.job_apply, name='job-apply'),
    path('my-applications/', views.my_applications, name='my-job-applications'),
    path('my-resume/', views.my_resume, name='my-resume'),
    path('manage/', views.manage_postings, name='manage-postings'),
    path('manage/add/', views.posting_add, name='posting-add'),
    path('manage/employers/add/', views.employer_add, name='employer-add'),
    path('manage/<int:pk>/applications/', views.posting_applications, name='posting-applications'),
    path('applications/<int:pk>/status/', views.update_application_status, name='update-application-status'),
]
