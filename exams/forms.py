from django import forms
from .models import ExamSession, GradeEntry

class ExamForm(forms.ModelForm):
    class Meta:
        model = ExamSession
        fields = '__all__'

class GradeEntryForm(forms.ModelForm):
    class Meta:
        model = GradeEntry
        fields = ['student', 'exam', 'attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks', 'marks', 'attempt_type']
        help_texts = {
            'attendance_marks': 'Raw marks out of the course\'s Attendance Weight (e.g. out of 10 by default) - not a percentage.',
            'assignment_marks': 'Raw marks out of the course\'s Assignment Weight (e.g. out of 20 by default).',
            'midterm_marks': 'Raw marks out of the course\'s Midterm Weight (e.g. out of 30 by default).',
            'final_marks': 'Raw marks out of the course\'s Final Weight (e.g. out of 40 by default).',
            'marks': 'Filled in automatically from the components above (they already add up to a 0-100 total). Only edit this directly for a single-figure exam with no component breakdown.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `marks` really is auto-filled by GradeEntry.save() whenever any
        # component is entered (see the model and the help text above) -
        # it shouldn't also be a required field a teacher has to type a
        # placeholder into just to get past validation.
        self.fields['marks'].required = False
        # The exact ceiling for each component depends on the course this
        # entry is for, so it can't be a fixed field validator - fill it
        # in here (as a max attribute for the browser, and for clean()
        # below) once we know which exam/course is selected.
        course = None
        exam = self.initial.get('exam') or getattr(self.instance, 'exam_id', None) and self.instance.exam
        if exam is not None:
            course = getattr(exam, 'course', None)
        if course is not None:
            caps = {
                'attendance_marks': course.attendance_weight,
                'assignment_marks': course.assignment_weight,
                'midterm_marks': course.midterm_weight,
                'final_marks': course.final_weight,
            }
            for field_name, cap in caps.items():
                self.fields[field_name].widget.attrs['max'] = cap
                self.fields[field_name].help_text = f'Raw marks out of {cap} for this course.'

    def clean(self):
        cleaned = super().clean()
        component_fields = ['attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks']
        components = [cleaned.get(f) for f in component_fields]
        if not any(c is not None for c in components) and cleaned.get('marks') is None:
            raise forms.ValidationError(
                'Enter either a component breakdown (attendance/assignment/midterm/final) or a single-figure Marks value.'
            )
        # Each raw component can't exceed the course's weight for it (that
        # weight IS the component's max marks - see the model). Checked
        # here so the teacher gets a clear, course-specific message
        # instead of a silently-clamped value after saving.
        exam = cleaned.get('exam')
        course = getattr(exam, 'course', None) if exam else None
        if course is not None:
            caps = {
                'attendance_marks': ('Attendance', course.attendance_weight),
                'assignment_marks': ('Assignment', course.assignment_weight),
                'midterm_marks': ('Midterm', course.midterm_weight),
                'final_marks': ('Final', course.final_weight),
            }
            for field_name, (label, cap) in caps.items():
                value = cleaned.get(field_name)
                if value is not None and value > cap:
                    self.add_error(field_name, f'{label} marks can\'t exceed {cap} for this course (its configured max for this component).')
        return cleaned