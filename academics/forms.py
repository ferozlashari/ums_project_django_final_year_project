from django import forms
from .models import Course, Department, Faculty, Program, CourseSection

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = '__all__'


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = '__all__'


class FacultyForm(forms.ModelForm):
    class Meta:
        model = Faculty
        fields = '__all__'


class ProgramForm(forms.ModelForm):
    class Meta:
        model = Program
        fields = '__all__'


class CourseSectionForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = '__all__'
