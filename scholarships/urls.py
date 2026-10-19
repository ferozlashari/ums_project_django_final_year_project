from django.urls import path
from . import views

urlpatterns = [
    path('', views.scholarship_list, name='scholarship-list'),
    path('<int:pk>/apply/', views.apply_scholarship, name='scholarship-apply'),
    path('my-applications/', views.my_applications, name='my-scholarship-applications'),
    path('manage/', views.manage_scholarships, name='manage-scholarships'),
    path('manage/add/', views.scholarship_add, name='scholarship-add'),
    path('manage/<int:pk>/applications/', views.scholarship_applications, name='scholarship-applications'),
    path('applications/<int:pk>/review/', views.review_scholarship_application, name='review-scholarship-application'),
]
