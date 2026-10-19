from django.urls import path
from . import views

urlpatterns = [
    path('', views.exam_list, name='exams'),
    path('add/', views.exam_add, name='exam-add'),
    path('results/', views.results, name='results'),
    path('results/add/', views.grade_add, name='grade-add'),
    path('results/<int:pk>/edit/', views.grade_edit, name='grade-edit'),
    path('results/<int:pk>/unlock/', views.grade_unlock, name='grade-unlock'),
    path('grade-scale/', views.grade_scale, name='grade-scale'),
    path('results/<int:pk>/correction/', views.grade_correction_request, name='grade-correction-request'),
    path('corrections/', views.grade_corrections, name='grade-corrections'),
    path('corrections/<int:pk>/<str:decision>/', views.grade_correction_decide, name='grade-correction-decide'),
    path('results/check/', views.result_checker, name='result-checker'),
    path('marksheet/<int:student_id>/', views.marksheet, name='marksheet'),
    path('retake/apply/<int:grade_entry_id>/', views.apply_retake, name='apply-retake'),
    path('retake/my-applications/', views.my_retake_applications, name='my-retake-applications'),
    path('retake/manage/', views.manage_retake_applications, name='manage-retake-applications'),
    path('retake/manage/<int:pk>/review/', views.review_retake_application, name='review-retake-application'),
    path('retake/<int:pk>/slip/', views.retake_slip, name='retake-slip'),
    path('exam-slip/', views.exam_slip, name='my-exam-slip'),
    path('exam-slip/<int:student_id>/', views.exam_slip, name='exam-slip'),
    path('gpa/', views.gpa_calculator, name='gpa-calculator'),
    path('gpa/<int:student_id>/', views.gpa_calculator, name='gpa-calculator-for'),
]
