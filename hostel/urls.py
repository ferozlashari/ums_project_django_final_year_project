from django.urls import path
from . import views

urlpatterns = [
    path('', views.my_application, name='hostel-my-application'),
    path('apply/', views.apply_hostel, name='hostel-apply'),
    path('manage/', views.manage_applications, name='hostel-manage'),
    path('manage/<int:pk>/review/', views.review_application, name='hostel-review'),
    path('manage/recommend/', views.run_recommendations, name='hostel-recommend'),
    path('rooms/', views.room_list, name='hostel-rooms'),
    path('rooms/add/', views.room_add, name='hostel-room-add'),
    path('hostels/', views.hostel_list, name='hostel-list'),
    path('hostels/add/', views.hostel_add, name='hostel-add'),
]
