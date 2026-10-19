from rest_framework import serializers
from academics.models import Faculty, Department, Program, Course, CourseSection

class FacultySerializer(serializers.ModelSerializer):
    class Meta: model = Faculty; fields = '__all__'

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta: model = Department; fields = '__all__'

class ProgramSerializer(serializers.ModelSerializer):
    class Meta: model = Program; fields = '__all__'

class CourseSerializer(serializers.ModelSerializer):
    class Meta: model = Course; fields = '__all__'

class CourseSectionSerializer(serializers.ModelSerializer):
    class Meta: model = CourseSection; fields = '__all__'