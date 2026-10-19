from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import webauthn_views
from . import otp_views

from . import automation_views as av
from . import setup_center as sc

urlpatterns = [
    path('setup/', sc.setup_hub, name='setup-hub'),
    path('setup/logins/', sc.login_list, name='setup-logins'),
    path('setup/logins/add/', sc.login_add, name='setup-login-add'),
    path('setup/logins/<int:pk>/role/', sc.login_role, name='setup-login-role'),
    path('setup/registrations/add/', sc.registration_add, name='setup-registration-add'),
    path('setup/<slug:key>/', sc.setup_list, name='setup-list'),
    path('setup/<slug:key>/add/', sc.setup_form, name='setup-add'),
    path('setup/<slug:key>/<int:pk>/edit/', sc.setup_form, name='setup-edit'),
    path('teacher/automation/', av.teacher_automation, name='teacher-automation'),
    path('teacher/attendance/today/', av.teacher_attendance_today, name='teacher-attendance-today'),
    path('teacher/attendance/summary/', av.teacher_attendance_summary, name='teacher-attendance-summary'),
    path('teacher/marks/', av.teacher_marks_all, name='teacher-marks-all'),
    path('teacher/marks/<int:section_id>/', av.teacher_marks, name='teacher-marks'),
    path('results/workflow/', av.results_workflow, name='results-workflow'),
    path('student/automation/', av.student_automation, name='student-automation'),
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/admin/', views.admin_dashboard, name='admin-dashboard'),
    path('dashboard/student/', views.student_dashboard, name='student-dashboard'),
    path('dashboard/staff/', views.staff_dashboard, name='staff-dashboard'),
    path('documents/', views.document_center, name='document-center'),
    path('audit-log/', views.audit_log, name='audit-log'),
    path('automation/', views.automation_center, name='automation-center'),

    path('login/', views.ThrottledLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('verify-email/<uidb64>/<token>/', views.verify_email, name='verify-email'),
    path('verify-email-code/', otp_views.verify_email_code, name='verify-email-code'),
    path('verify-email-code/resend/', otp_views.verify_email_resend, name='verify-email-resend'),
    path('password-reset/code/', otp_views.password_reset_code, name='password-reset-code'),
    path('account/confirm-email/', otp_views.change_email_confirm, name='change-email-confirm'),

    # Forgot / change password (Django's built-in views, site-styled templates)
    path('password-reset/', views.DevAwarePasswordResetView.as_view(
        success_url='/password-reset/done/',
    ), name='password_reset'),
    path('password-reset/done/', views.DevAwarePasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/password_reset_confirm.html',
        success_url='/password-reset/complete/',
    ), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/password_reset_complete.html'
    ), name='password_reset_complete'),
    path('password-change/', auth_views.PasswordChangeView.as_view(
        template_name='core/password_change_form.html',
        success_url='/password-change/done/',
    ), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='core/password_change_done.html'
    ), name='password_change_done'),

    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit-profile'),
    path('notices/', views.notices_list, name='notices-list'),
    path('notices/add/', views.notice_add, name='notice-add'),
    path('reports/', views.reports, name='reports'),
    path('analytics/', views.analytics, name='analytics'),
    path('automation/', views.automation_dashboard, name='automation-dashboard'),
    path('reports/students/', views.report_student_count, name='report-student-count'),
    path('reports/attendance/', views.report_attendance, name='report-attendance'),
    path('reports/fees/', views.report_fees, name='report-fees'),
    path('search/', views.global_search, name='global-search'),
    path('settings/', views.site_settings, name='site-settings'),
    path('settings/account/', views.account_settings, name='account-settings'),
    path('notifications/', views.notifications_list, name='notifications-list'),
    path('notifications/<int:pk>/read/', views.notification_read, name='notification-read'),
    path('notifications/mark-all-read/', views.notifications_mark_all_read, name='notifications-mark-all-read'),

    # Two-factor auth (fingerprint / face / security key)
    path('verify-2fa/', webauthn_views.verify_2fa_page, name='verify-2fa'),
    path('webauthn/register/begin/', webauthn_views.webauthn_register_begin, name='webauthn-register-begin'),
    path('webauthn/register/complete/', webauthn_views.webauthn_register_complete, name='webauthn-register-complete'),
    path('webauthn/login/begin/', webauthn_views.webauthn_login_begin, name='webauthn-login-begin'),
    path('webauthn/login/complete/', webauthn_views.webauthn_login_complete, name='webauthn-login-complete'),
    path('webauthn/device/<int:pk>/delete/', webauthn_views.webauthn_device_delete, name='webauthn-device-delete'),
    path('webauthn/toggle/', webauthn_views.webauthn_toggle, name='webauthn-toggle'),
    path('webauthn/verify/begin/', webauthn_views.webauthn_verify_begin, name='webauthn-verify-begin'),
    path('webauthn/verify/complete/', webauthn_views.webauthn_verify_complete, name='webauthn-verify-complete'),
]
