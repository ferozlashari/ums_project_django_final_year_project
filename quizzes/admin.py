from django.contrib import admin
from .models import Quiz, Question, QuizAttempt, StudentAnswer

admin.site.register(Question)
admin.site.register(StudentAnswer)


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'section', 'is_published', 'created_at')
    list_filter = ('is_published',)


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('student', 'quiz', 'score', 'submitted_at')
