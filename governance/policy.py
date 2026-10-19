"""Versioned, scoped policy lookup. resolve() returns the value from the most
specific scope (program > department > faculty > university) in effect today,
highest version wins; falls back to `default` so existing behaviour is kept."""
from django.db import models
from django.utils import timezone

from .models import PolicyRule, PolicyVersion

_SPECIFICITY = {
    'student': 8, 'section': 7, 'course': 6, 'semester': 5,
    'program': 4, 'department': 3, 'faculty': 2, 'university': 1,
    'student_category': 4,
}


def resolve(key, program=None, department=None, faculty=None, semester=None, course=None, section=None,
            student=None, student_category=None, on=None, default=None):
    """Resolve the effective policy for the most specific supplied scope.

    The lookup is deliberately read-only and version-aware. More specific
    scopes override broader scopes, while effective dates and version numbers
    keep historical policy changes reproducible.
    """
    on = on or timezone.localdate()
    try:
        rule = PolicyRule.objects.get(key=key)
    except PolicyRule.DoesNotExist:
        return default
    if student is not None:
        enrollment = getattr(student, 'current_enrollment', None)
        program = program or getattr(enrollment, 'program', None)
    if section is not None:
        course = course or getattr(section, 'course', None)
        semester = semester or getattr(section, 'semester', None)
    if course is not None:
        program = program or getattr(course, 'program', None)
    if program is not None:
        department = department or getattr(program, 'department', None)
    if department is not None:
        faculty = faculty or getattr(department, 'faculty', None)

    wanted = models.Q(scope_type='university')
    for scope_type, obj in (
        ('faculty', faculty), ('department', department), ('program', program),
        ('semester', semester), ('course', course), ('section', section),
        ('student', student),
    ):
        if obj is not None and getattr(obj, 'pk', None) is not None:
            wanted |= models.Q(scope_type=scope_type, scope_id=obj.pk)
    if student_category:
        # Student category is represented by a stable category identifier in scope_id.
        try:
            wanted |= models.Q(scope_type='student_category', scope_id=int(student_category))
        except (TypeError, ValueError):
            pass

    candidates = (PolicyVersion.objects.filter(rule=rule, effective_from__lte=on).filter(wanted)
                  .filter(models.Q(effective_until__isnull=True) | models.Q(effective_until__gte=on)))
    best = None
    for v in candidates:
        rank = (_SPECIFICITY.get(v.scope_type, 0), v.version)
        if best is None or rank > best[0]:
            best = (rank, v)
    if best is None:
        return default
    try:
        return rule.cast(best[1].value)
    except (ValueError, ArithmeticError):
        return default


def new_version(rule, value, user=None, scope_type='university', scope_id=None,
                effective_from=None, effective_until=None, reason=''):
    last = rule.versions.aggregate(m=models.Max('version'))['m'] or 0
    return PolicyVersion.objects.create(
        rule=rule, version=last + 1, value=str(value), scope_type=scope_type, scope_id=scope_id,
        effective_from=effective_from or timezone.localdate(), effective_until=effective_until,
        reason=reason, created_by=user)


DEFAULT_RULES = [
    ('attendance.minimum_percent', 'attendance', 'Minimum attendance %', 'int', 'Below this a student is short of attendance.'),
    ('registration.max_credit_hours', 'registration', 'Maximum credit hours per semester', 'int', ''),
    ('exams.marks_lock_days', 'examination', 'Days before teacher marks lock', 'int', ''),
    ('finance.late_fee_grace_days', 'finance', 'Late fee grace days', 'int', ''),
]


def ensure_default_rules():
    for key, cat, name, vtype, desc in DEFAULT_RULES:
        PolicyRule.objects.get_or_create(key=key, defaults={
            'category': cat, 'name': name, 'value_type': vtype, 'description': desc})
