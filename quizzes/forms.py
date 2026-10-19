from django import forms
from .models import Quiz, Question


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['section', 'title', 'time_limit_minutes', 'is_published']


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['text', 'choice_a', 'choice_b', 'choice_c', 'choice_d', 'correct_choice', 'order']
        widgets = {'text': forms.Textarea(attrs={'rows': 2})}
