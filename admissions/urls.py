from django.urls import path
from . import views

urlpatterns = [
    path('', views.application_list, name='applications-list'),
    path('seats/', views.seat_summary, name='seat-summary'),
    path('apply/', views.apply, name='apply'),
    path('apply-now/', views.apply_public, name='apply-public'),
    path('entry-test-slip/', views.entry_test_slip, name='my-entry-test-slip'),
    path('entry-test-slip/<int:application_id>/', views.entry_test_slip, name='entry-test-slip'),
    path('entry-test/<int:pk>/reschedule/', views.entry_test_reschedule, name='entry-test-reschedule'),
    path('entry-test/<int:pk>/result/', views.enter_entry_test_result, name='entry-test-result'),
    path('merit-list/', views.merit_list, name='merit-list'),
    path('selection/run/', views.run_selection, name='run-selection'),
    path('selection/preferences/run/', views.run_preference_allocation, name='run-preference-allocation'),
    path('applications/<int:pk>/preferences/', views.application_preferences, name='application-preferences'),
]
