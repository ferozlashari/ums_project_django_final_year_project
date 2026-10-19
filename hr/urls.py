from django.urls import path
from . import views

urlpatterns = [
    path('', views.hr_index, name='hr-index'),
    path('teachers/', views.teacher_list, name='teacher-list'),
    path('teachers/add/', views.teacher_add, name='teacher-add'),
    path('teachers/<int:pk>/edit/', views.teacher_edit, name='teacher-edit'),
    path('teachers/<int:pk>/delete/', views.teacher_delete, name='teacher-delete'),
    path('dashboard/', views.teacher_dashboard, name='teacher-dashboard'),
    path('payroll/', views.payroll_list, name='payroll-list'),
    path('payroll/add/', views.payroll_add, name='payroll-add'),
    path('payroll/generate-month/', views.payroll_generate_month, name='payroll-generate-month'),
    path('payroll/<int:pk>/pay/', views.payroll_pay, name='payroll-pay'),
    path('my-salary/', views.my_salary, name='my-salary'),
]
