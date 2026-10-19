from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Quiz, Question, QuizAttempt, StudentAnswer
from .forms import QuizForm, QuestionForm
from django.core.exceptions import PermissionDenied
from core.permissions import can_manage_section, staff_or_admin_required, user_role
from core.models import notify


@login_required
def quiz_list(request):
    role = user_role(request.user)
    quizzes = Quiz.objects.select_related('section', 'section__course').all()
    my_attempts = {}

    if role == 'student':
        quizzes = quizzes.filter(is_published=True)
        try:
            student = request.user.student_profile
            # Registered-section-scoped, not whole-program (see the
            # identical fix and reasoning in assignments/views.py
            # assignment_list) - a student should only see quizzes for
            # sections they're actually registered in.
            from academics.models import CourseRegistration
            registered_section_ids = CourseRegistration.objects.filter(
                student=student, status='registered',
            ).values_list('section_id', flat=True)
            quizzes = quizzes.filter(section_id__in=registered_section_ids)
            my_attempts = {a.quiz_id: a for a in QuizAttempt.objects.filter(student=student)}
        except Exception:
            quizzes = Quiz.objects.none()
    elif role in ('faculty', 'staff'):
        try:
            quizzes = quizzes.filter(section__instructor=request.user.staff_profile)
        except Exception:
            pass

    rows = [{'quiz': q, 'attempt': my_attempts.get(q.id)} for q in quizzes]
    return render(request, 'quizzes/list.html', {'rows': rows, 'role': role})


@staff_or_admin_required
def quiz_add(request):
    if request.method == 'POST':
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.created_by = request.user
            quiz.save()
            messages.success(request, 'Quiz created - now add questions to it.')
            return redirect('quiz-questions', pk=quiz.pk)
    else:
        form = QuizForm()
        if user_role(request.user) in ('faculty', 'staff'):
            try:
                from academics.models import CourseSection
                form.fields['section'].queryset = CourseSection.objects.filter(instructor=request.user.staff_profile)
            except Exception:
                pass
    return render(request, 'core/form_base.html', {'form': form, 'title': 'New Quiz', 'cancel_url': '/quizzes/'})


@staff_or_admin_required
def quiz_questions(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not can_manage_section(request.user, quiz.section, write=(request.method == 'POST')):
        raise PermissionDenied('This quiz belongs to another teacher\'s section.')
    if request.method == 'POST':
        form = QuestionForm(request.POST)
        if form.is_valid():
            q = form.save(commit=False)
            q.quiz = quiz
            q.save()
            messages.success(request, 'Question added.')
            return redirect('quiz-questions', pk=quiz.pk)
    else:
        form = QuestionForm(initial={'order': quiz.questions.count() + 1})
    return render(request, 'quizzes/questions.html', {'quiz': quiz, 'form': form, 'questions': quiz.questions.all()})


@staff_or_admin_required
@require_POST
def quiz_publish(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    if not can_manage_section(request.user, quiz.section, write=True):
        raise PermissionDenied('Only the section\'s own teacher can publish this quiz.')
    if not quiz.questions.exists():
        messages.error(request, "Add at least one question before publishing.")
        return redirect('quiz-questions', pk=pk)
    quiz.is_published = not quiz.is_published
    quiz.save(update_fields=['is_published'])
    if quiz.is_published:
        from registration.models import Student
        from academics.models import CourseRegistration
        from core.models import notify_many
        registered_student_ids = CourseRegistration.objects.filter(
            section=quiz.section, status='registered',
        ).values_list('student_id', flat=True)
        students = Student.objects.filter(id__in=registered_student_ids)
        notify_many(
            [s.user for s in students], f'New quiz available: {quiz.title}',
            f'{quiz.section.course.code} - {quiz.total_marks} question(s), {quiz.time_limit_minutes} min.',
            level='info', url='/quizzes/',
        )
    messages.success(request, f'Quiz {"published" if quiz.is_published else "unpublished"}.')
    return redirect('quiz-list')


@login_required
def take_quiz(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk, is_published=True)
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students take quizzes.')
    try:
        student = request.user.student_profile
    except Exception:
        messages.error(request, 'No student record linked to this account.')
        return redirect('quiz-list')

    if QuizAttempt.objects.filter(quiz=quiz, student=student, submitted_at__isnull=False).exists():
        messages.info(request, "You've already completed this quiz.")
        return redirect('quiz-result', pk=quiz.pk)

    questions = quiz.questions.all()
    if request.method == 'POST':
        attempt, _ = QuizAttempt.objects.get_or_create(quiz=quiz, student=student)
        score = 0
        for q in questions:
            selected = request.POST.get(f'q{q.id}')
            if selected:
                StudentAnswer.objects.update_or_create(
                    attempt=attempt, question=q, defaults={'selected_choice': selected},
                )
                if selected == q.correct_choice:
                    score += 1
        attempt.score = score
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=['score', 'submitted_at'])
        notify(
            request.user, f'Quiz completed: {quiz.title}',
            f'You scored {score} / {quiz.total_marks}.', level='success', url='/quizzes/',
        )
        messages.success(request, f'Quiz submitted! Score: {score} / {quiz.total_marks}.')
        return redirect('quiz-result', pk=quiz.pk)

    return render(request, 'quizzes/take.html', {'quiz': quiz, 'questions': questions})


@login_required
def quiz_result(request, pk):
    quiz = get_object_or_404(Quiz, pk=pk)
    role = user_role(request.user)
    if role == 'student':
        try:
            student = request.user.student_profile
        except Exception:
            raise PermissionDenied('No student record linked to this account.')
        attempt = get_object_or_404(QuizAttempt, quiz=quiz, student=student)
    else:
        raise PermissionDenied('Only the student who took the quiz can view this result here - use quiz management to review all attempts.')
    answers = attempt.answers.select_related('question')
    return render(request, 'quizzes/result.html', {'quiz': quiz, 'attempt': attempt, 'answers': answers})
