"""Configurable grade scale. Teachers enter raw marks only; letter grade,
grade point and pass/fail are derived from the scale in effect on the exam's
date, so a new scale never silently re-grades old exams."""
import sys
import time
from decimal import Decimal

# (grade, min_percent, max_percent, grade_point, is_pass, allows_improvement)
DEFAULT_BANDS = [
    ('A+', 90, 100, 4.0, True, False), ('A', 85, 89.99, 4.0, True, False),
    ('B+', 80, 84.99, 3.5, True, False), ('B', 75, 79.99, 3.0, True, False),
    ('C+', 70, 74.99, 2.5, True, False), ('C', 65, 69.99, 2.0, True, False),
    ('D+', 60, 64.99, 1.5, True, True), ('D', 50, 59.99, 1.0, True, True),
    ('F', 0, 49.99, 0.0, False, False),
]


class Band:
    __slots__ = ('grade', 'min_percent', 'max_percent', 'grade_point', 'is_pass', 'allows_improvement')

    def __init__(self, grade, min_percent, max_percent, grade_point, is_pass, allows_improvement):
        self.grade = grade
        self.min_percent = float(min_percent)
        self.max_percent = float(max_percent)
        self.grade_point = float(grade_point)
        self.is_pass = bool(is_pass)
        self.allows_improvement = bool(allows_improvement)


_cache = {}
_TTL = 0 if 'test' in sys.argv else 30


def clear_cache(*args, **kwargs):
    _cache.clear()


def bands_for(on=None):
    from django.utils import timezone
    from .models import GradeScale
    on = on or timezone.localdate()
    hit = _cache.get(on)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return hit[1]
    scale = (GradeScale.objects.filter(is_active=True, effective_from__lte=on)
             .exclude(effective_until__lt=on).order_by('-effective_from', '-id').first())
    if scale is not None:
        bands = [Band(b.grade, b.min_percent, b.max_percent, b.grade_point, b.is_pass, b.allows_improvement)
                 for b in scale.bands.all()]
    else:
        bands = [Band(*row) for row in DEFAULT_BANDS]
    bands.sort(key=lambda b: b.min_percent, reverse=True)
    _cache[on] = (time.monotonic(), bands)
    return bands


def band_for(percentage, on=None):
    pct = float(percentage or 0)
    bands = bands_for(on)
    for b in bands:
        if pct >= b.min_percent:
            return b
    return bands[-1]


def validate_bands(rows):
    """rows: dicts with grade, min_percent, grade_point, is_pass. Returns error strings."""
    if len(rows) < 2:
        return ['A scale needs at least two grades (a passing grade and F).']
    errors = []
    names = [r['grade'].strip().upper() for r in rows]
    if len(set(names)) != len(names):
        errors.append('Grade letters must be unique.')
    mins = [Decimal(str(r['min_percent'])) for r in rows]
    if len(set(mins)) != len(mins):
        errors.append('Two grades cannot start at the same percentage.')
    if any(m < 0 or m > 100 for m in mins):
        errors.append('Minimum percentages must be between 0 and 100.')
    if min(mins) != 0:
        errors.append('The lowest grade must start at 0% so every mark receives a grade.')
    ordered = sorted(rows, key=lambda r: Decimal(str(r['min_percent'])), reverse=True)
    last = None
    for r in ordered:
        gp = Decimal(str(r['grade_point']))
        if gp < 0 or gp > 10:
            errors.append(f"Grade point for {r['grade']} must be between 0 and 10.")
        if last is not None and gp > last:
            errors.append(f"Grade point for {r['grade']} is higher than a grade with a higher percentage.")
        last = gp
    if ordered[-1]['is_pass']:
        errors.append('The lowest grade (0%) must be a failing grade.')
    if not any(r['is_pass'] for r in rows):
        errors.append('At least one grade must be passing.')
    seen_pass = False
    for r in reversed(ordered):
        if r['is_pass']:
            seen_pass = True
        elif seen_pass:
            errors.append('A failing grade cannot sit above a passing grade.')
            break
    return errors
