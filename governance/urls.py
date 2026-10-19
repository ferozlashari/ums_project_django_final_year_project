from django.urls import path

from . import views

urlpatterns = [
    path('', views.security_center, name='security-center'),
    path('roles/', views.role_list, name='role-list'),
    path('roles/new/', views.role_edit, name='role-add'),
    path('roles/<int:pk>/edit/', views.role_edit, name='role-edit'),
    path('roles/<int:pk>/delete/', views.role_delete, name='role-delete'),
    path('assignments/', views.assignment_list, name='role-assignments'),
    path('assignments/new/', views.assignment_add, name='role-assign'),
    path('assignments/<int:pk>/revoke/', views.assignment_revoke, name='role-revoke'),
    path('subadmins/new/', views.subadmin_create, name='subadmin-create'),
    path('policies/', views.policy_center, name='policy-center'),
    path('provision/', views.provision_account, name='provision-account'),
    path('emergency/', views.emergency_access, name='emergency-access'),
    path('map/', views.governance_map, name='governance-map'),
    path('my-access/', views.my_access, name='my-access'),
    path('matrix/', views.permission_matrix, name='permission-matrix'),
    path('executive/', views.executive_dashboard, name='executive-dashboard'),
]
