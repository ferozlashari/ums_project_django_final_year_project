from django.urls import path
from . import views

urlpatterns = [
    path('', views.timetable_list, name='timetable-list'),
    path('planner/', views.timetable_planner, name='timetable-planner'),
    path('add/', views.timetable_add, name='timetable-add'),
    path('rooms/', views.room_list, name='room-list'),
    path('rooms/add/', views.room_add, name='room-add'),
]
