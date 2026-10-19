from django.shortcuts import render

from registration.models import Student
from . import services


def verify_id(request, token):
    """Public verification page - no login required, since this is what a
    security guard or exam invigilator scans. Only ever shows the minimal
    fields needed to confirm identity + current standing, re-fetched live
    from the database rather than trusted from the token itself."""
    student_pk = services.verify_token(token)
    student = None
    if student_pk is not None:
        student = Student.objects.select_related("program", "program__department").filter(pk=student_pk).first()
    return render(request, "digital_id/verify.html", {
        "valid": student is not None,
        "student": student,
    })
