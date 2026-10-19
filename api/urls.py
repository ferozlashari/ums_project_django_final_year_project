from rest_framework import routers
from rest_framework.authtoken.views import obtain_auth_token
from django.urls import path, include
from .views import FacultyViewSet, DepartmentViewSet, ProgramViewSet, CourseViewSet, CourseSectionViewSet
from .workflow import MyAcademicSummaryAPI, EligibleSectionsAPI, MyExamEligibilityAPI, MyFeesAPI, RegisterCourseAPI, SubmitPaymentAPI, MyAttendanceAPI, MyLibraryAPI, MyHostelAPI, MyTransportAPI, MyTimetableAPI, MyQuizzesAPI, MyNotificationsAPI, MyComplaintsAPI

router = routers.DefaultRouter()
# Explicit basenames here so the auto-generated URL *names* (e.g.
# 'course-list') don't collide with the human-facing pages in
# academics/urls.py, which use those exact same names. Without this,
# {% url 'course-list' %} in the sidebar resolves to the API's
# /api/v1/courses/ instead of the human /academics/courses/ page - the
# URL *paths* below (r'courses', r'faculties', ...) are unaffected either
# way, only the internal name used for reverse()/{% url %} changes.
router.register(r'faculties', FacultyViewSet, basename='api-faculty')
router.register(r'departments', DepartmentViewSet, basename='api-department')
router.register(r'programs', ProgramViewSet, basename='api-program')
router.register(r'courses', CourseViewSet, basename='api-course')
router.register(r'sections', CourseSectionViewSet, basename='api-section')

urlpatterns = [
    path('auth/token/', obtain_auth_token, name='api-token'),
    path('v1/', include(router.urls)),
    path('v1/me/academic-summary/', MyAcademicSummaryAPI.as_view(), name='api-my-academic-summary'),
    path('v1/me/eligible-sections/', EligibleSectionsAPI.as_view(), name='api-eligible-sections'),
    path('v1/me/exam-eligibility/', MyExamEligibilityAPI.as_view(), name='api-my-exam-eligibility'),
    path('v1/me/fees/', MyFeesAPI.as_view(), name='api-my-fees'),
    path('v1/me/register-course/', RegisterCourseAPI.as_view(), name='api-register-course'),
    path('v1/me/invoices/<int:invoice_id>/payment/', SubmitPaymentAPI.as_view(), name='api-submit-payment'),
    path('v1/me/attendance/', MyAttendanceAPI.as_view(), name='api-my-attendance'),
    path('v1/me/library/', MyLibraryAPI.as_view(), name='api-my-library'),
    path('v1/me/hostel/', MyHostelAPI.as_view(), name='api-my-hostel'),
    path('v1/me/transport/', MyTransportAPI.as_view(), name='api-my-transport'),
    path('v1/me/timetable/', MyTimetableAPI.as_view(), name='api-my-timetable'),
    path('v1/me/quizzes/', MyQuizzesAPI.as_view(), name='api-my-quizzes'),
    path('v1/me/notifications/', MyNotificationsAPI.as_view(), name='api-my-notifications'),
    path('v1/me/complaints/', MyComplaintsAPI.as_view(), name='api-my-complaints'),
]
