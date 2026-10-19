from django.urls import path
from . import views

urlpatterns = [
    path('', views.quiz_list, name='quiz-list'),
    path('add/', views.quiz_add, name='quiz-add'),
    path('<int:pk>/questions/', views.quiz_questions, name='quiz-questions'),
    path('<int:pk>/publish/', views.quiz_publish, name='quiz-publish'),
    path('<int:pk>/take/', views.take_quiz, name='quiz-take'),
    path('<int:pk>/result/', views.quiz_result, name='quiz-result'),
]
