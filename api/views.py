from rest_framework import viewsets
from academics.models import Faculty, Department, Program, Course, CourseSection
from .serializers import FacultySerializer, DepartmentSerializer, ProgramSerializer, CourseSerializer, CourseSectionSerializer
from core.api_permissions import IsAuthenticatedReadOnlyOrAdminWrite


class FacultyViewSet(viewsets.ModelViewSet):
    queryset = Faculty.objects.order_by('name'); serializer_class = FacultySerializer
    permission_classes = [IsAuthenticatedReadOnlyOrAdminWrite]

class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.order_by('name'); serializer_class = DepartmentSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrAdminWrite]

class ProgramViewSet(viewsets.ModelViewSet):
    queryset = Program.objects.order_by('name'); serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrAdminWrite]

class CourseViewSet(viewsets.ModelViewSet):
    queryset = Course.objects.order_by('code'); serializer_class = CourseSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrAdminWrite]

class CourseSectionViewSet(viewsets.ModelViewSet):
    queryset = CourseSection.objects.order_by('course__code', 'code'); serializer_class = CourseSectionSerializer
    permission_classes = [IsAuthenticatedReadOnlyOrAdminWrite]