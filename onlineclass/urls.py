from django.urls import path
from . import views

urlpatterns = [
    path('', views.class_list, name='class-list'),
    path('schedule/', views.class_schedule, name='class-schedule'),
    path('<int:pk>/join/', views.class_join, name='class-join'),
    path('<int:pk>/end/', views.class_end, name='class-end'),
]
