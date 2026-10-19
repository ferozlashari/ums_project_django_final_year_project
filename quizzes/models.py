from django.db import models


class Quiz(models.Model):
    """A multiple-choice quiz for one section - auto-graded, one attempt
    per student, matching a typical LMS 'online quiz' feature."""
    section = models.ForeignKey('academics.CourseSection', on_delete=models.CASCADE, related_name='quizzes')
    title = models.CharField(max_length=200)
    time_limit_minutes = models.PositiveIntegerField(default=15)
    is_published = models.BooleanField(default=False, help_text='Students can only see/take published quizzes.')
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.section})'

    @property
    def total_marks(self):
        return self.questions.count()

    class Meta:
        verbose_name_plural = 'Quizzes'


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField(max_length=500)
    choice_a = models.CharField(max_length=200)
    choice_b = models.CharField(max_length=200)
    choice_c = models.CharField(max_length=200, blank=True)
    choice_d = models.CharField(max_length=200, blank=True)
    correct_choice = models.CharField(max_length=1, choices=[('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')])
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.text[:60]

    def choice_text(self, letter):
        return getattr(self, f'choice_{letter}', '')


class QuizAttempt(models.Model):
    """One student's single attempt at a quiz - auto-scored the moment
    it's submitted, no manual grading needed."""
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='quiz_attempts')
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [('quiz', 'student')]
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student.full_name} - {self.quiz.title} ({self.score}/{self.quiz.total_marks})'

    @property
    def percentage(self):
        total = self.quiz.total_marks
        return round((self.score / total) * 100, 1) if total else 0


class StudentAnswer(models.Model):
    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_choice = models.CharField(max_length=1, choices=[('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')])

    class Meta:
        unique_together = [('attempt', 'question')]

    @property
    def is_correct(self):
        return self.selected_choice == self.question.correct_choice
