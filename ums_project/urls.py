from django.contrib import admin
from django.urls import path, include
from core.health import health, readiness
from core.cron import cron_tick

admin.site.site_header = 'UMS 2026 Administration'
admin.site.site_title = 'UMS Admin'
admin.site.index_title = 'University Management System — Administration Console'

urlpatterns = [
    path('health/', health, name='health'),
    path('ready/', readiness, name='readiness'),
    path('internal/cron/', cron_tick, name='cron-tick'),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('academics/', include('academics.urls')),
    path('admissions/', include('admissions.urls')),
    path('registration/', include('registration.urls')),
    path('timetable/', include('timetable.urls')),
    path('exams/', include('exams.urls')),
    path('finance/', include('finance.urls')),
    path('hr/', include('hr.urls')),
    path('attendance/', include('attendance.urls')),
    path('api/', include('api.urls')),
    path('ai/', include('ai_assistant.urls')),
    path('library/', include('library.urls')),
    path('hostel/', include('hostel.urls')),
    path('complaints/', include('complaints.urls')),
    path('scholarships/', include('scholarships.urls')),
    path('classes/', include('onlineclass.urls')),
    path('alumni/', include('alumni.urls')),
    path('parents/', include('parents.urls')),
    path('careers/', include('careers.urls')),
    path('risk/', include('risk_analytics.urls')),
    path('biometrics/', include('biometrics.urls')),
    path('transport/', include('transport.urls')),
    path('assignments/', include('assignments.urls')),
    path('quizzes/', include('quizzes.urls')),
    path('oversight/', include('oversight.urls')),
    path('id/', include('digital_id.urls')),
    path('workflow/', include('workflow.urls')),
    path('governance/', include('governance.urls')),
]

from django.urls import re_path
from core.media import protected_media

# Uploads are private (CNIC scans, medical certificates, submissions). They
# are served ONLY through the authenticated gateway - never a public mount,
# in development or production. See core/media.py.
urlpatterns += [re_path(r'^media/(?P<path>.+)$', protected_media, name='protected-media')]
