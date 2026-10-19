from django.urls import path
from . import views

urlpatterns = [
    path('', views.my_transport, name='my-transport'),
    path('routes/', views.route_list, name='transport-route-list'),
    path('routes/add/', views.route_add, name='transport-route-add'),
    path('stops/add/', views.stop_add, name='transport-stop-add'),
    path('vehicles/', views.vehicle_list, name='transport-vehicle-list'),
    path('vehicles/add/', views.vehicle_add, name='transport-vehicle-add'),
    path('assignments/', views.assignment_list, name='transport-assignment-list'),
    path('assignments/add/', views.assign_transport, name='transport-assign'),
    path('recommendations/', views.recommendations, name='transport-recommendations'),
    path('assignments/bulk/', views.bulk_assign_transport, name='transport-bulk-assign'),
    path('assignments/<int:pk>/remove/', views.unassign_transport, name='transport-unassign'),
]
