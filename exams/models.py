from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

# Letter grades / points / pass mark come from the admin-configurable GradeScale
# (exams/grading.py), resolved for the exam's date - nothing is hard-coded.
# Components are entered as RAW marks (not a 0-100 percentage) - each
# component's own maximum is the course's configured weight for it (see
# Course.attendance_weight etc., which are always validated to sum to
# 100). So "Attendance 8" means 8 out of a 10-mark attendance component,
# "Final 32" means 32 out of a 40-mark final, and so on - the four raw
# scores add up directly to a 0-100 total, the same way a teacher
# already thinks about marking a paper. There is no single static upper
# bound (it depends on the course), so only a non-negative floor is
# enforced here; the real per-component ceiling is checked dynamically
# in GradeEntryForm.clean() and clamped defensively in save() below.
_PCT_VALIDATORS = [MinValueValidator(0)]

class ExamSession(models.Model):
    name = models.CharField(max_length=200)
    course = models.ForeignKey('academics.Course', on_delete=models.CASCADE)
    semester = models.ForeignKey('academics.Semester', on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    duration_mins = models.IntegerField(default=120)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    def __str__(self): return f"{self.name} - {self.course.code}"

class GradeEntry(models.Model):
    ATTEMPT_CHOICES = [('regular', 'Regular'), ('improvement', 'Improvement'), ('retake', 'Retake')]
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE)
    exam = models.ForeignKey(ExamSession, on_delete=models.CASCADE)
    registration = models.ForeignKey('academics.CourseRegistration', on_delete=models.SET_NULL, null=True, blank=True, related_name='grade_entries')
    marks = models.DecimalField(max_digits=6, decimal_places=2)
    grade = models.CharField(
        max_length=10, blank=True, editable=False,
        help_text='Always recomputed from marks/max_marks on save - never independently editable, so a stored grade can never drift from the actual percentage.',
    )
    attempt_type = models.CharField(max_length=20, choices=ATTEMPT_CHOICES, default='regular')
    entered_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)
    entered_at = models.DateTimeField(auto_now_add=True)

    # Component breakdown. All optional so single-figure entries (e.g. a
    # standalone quiz/exam session) keep working unchanged. When a teacher
    # fills in some or all of these, `marks` is recalculated as their sum
    # on save() - the total is always derived from the components that
    # were actually entered, never hand-typed separately from them.
    # Each is RAW MARKS out of that component's own maximum, which is the
    # course's configured weight (Course.attendance_weight etc., always
    # summing to 100) - see the module-level comment above. A course not
    # yet customized uses the default 10/20/30/40 split, so an entry of
    # "Attendance 8, Assignment 16, Midterm 24, Final 32" sums straight
    # to 80/100 with no separate percentage conversion for the teacher
    # to do in their head.
    attendance_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=_PCT_VALIDATORS, help_text="Raw marks out of this course's attendance component (see the course's Attendance Weight).")
    assignment_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=_PCT_VALIDATORS, help_text="Raw marks out of this course's assignment component (Assignment Weight).")
    midterm_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=_PCT_VALIDATORS, help_text="Raw marks out of this course's midterm component (Midterm Weight).")
    final_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, validators=_PCT_VALIDATORS, help_text="Raw marks out of this course's final component (Final Weight).")

    # Admin override of the automatic lock (see is_locked below). A staff
    # member can flip this back to True after fixing/reopening an entry -
    # it does not need to stay True forever, so it is not a one-way switch.
    admin_unlocked = models.BooleanField(default=False, help_text='Admin override - bypasses the automatic marks-entry lock for this entry.')

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.registration_id:
            if self.registration.student_id != self.student_id:
                raise ValidationError('Grade registration does not belong to this student.')
            if self.registration.section.course_id != self.exam.course_id:
                raise ValidationError('Grade registration course does not match the exam course.')
            if self.registration.semester_id and self.exam.semester_id and self.registration.semester_id != self.exam.semester_id:
                raise ValidationError('Grade registration semester does not match the exam semester.')

    def save(self, *args, **kwargs):
        from decimal import Decimal
        components = [self.attendance_marks, self.assignment_marks, self.midterm_marks, self.final_marks]
        if any(c is not None for c in components):
            # Each entered component is RAW MARKS out of its own maximum
            # (the course's configured weight for that component - see
            # the field help_text and the module-level comment above).
            # Since the four weights always sum to 100 (Course.clean()),
            # clamping each raw component to its own weight first and then
            # simply adding them together already yields a 0-100 overall
            # percentage - no separate multiply-by-weight step needed, and
            # no way for one inflated component to silently dominate the
            # total. That percentage is then scaled to this exam's
            # max_marks so it stays comparable to exams that don't use
            # components at all. Kept entirely in Decimal: Python cannot
            # multiply a Decimal by a float.
            course = self.exam.course
            weight_caps = {
                'attendance_marks': course.attendance_weight,
                'assignment_marks': course.assignment_weight,
                'midterm_marks': course.midterm_weight,
                'final_marks': course.final_weight,
            }
            clamped_total = Decimal('0')
            for field_name, cap in weight_caps.items():
                value = getattr(self, field_name)
                if value is None:
                    continue
                clamped = max(Decimal('0'), min(Decimal(value), Decimal(cap)))
                setattr(self, field_name, clamped)
                clamped_total += clamped
            self.marks = round(clamped_total / Decimal('100') * Decimal(self.exam.max_marks), 2)

        # Safety net independent of form/model-field validation (which a
        # direct .save() call, a script, or the API can bypass): `marks`
        # can never exceed this exam's max_marks or go negative, no matter
        # how it was set. Without this, a bad component value (or a bad
        # direct `marks` write) could push the percentage past 100% and
        # produce a nonsensical top grade for a failing/impossible score -
        # exactly what happened before this was added.
        max_marks = Decimal(self.exam.max_marks)
        if self.marks is not None:
            self.marks = max(Decimal('0'), min(Decimal(self.marks), max_marks))

        # `grade` is always derived from the marks, never typed in. It is
        # recomputed on every save so it cannot drift from the percentage.
        self.grade = self.letter_grade
        super().save(*args, **kwargs)

    @property
    def lock_date(self):
        if not self.entered_at:
            return None
        from django.utils import timezone as _tz
        from core.models import SiteSettings
        return self.entered_at + _tz.timedelta(days=SiteSettings.load().marks_lock_days)

    @property
    def is_locked(self):
        """Marks portal automation: a teacher's entry locks itself a fixed
        number of days after it was first entered (default 60 / ~2
        months), so results can't be silently altered long after the
        fact. Only an explicit admin override (admin_unlocked) or full
        admin/staff access reopens it - see grade_edit."""
        if self.admin_unlocked:
            return False
        if self.is_published:
            return True  # published results change only through an approved correction
        lock_date = self.lock_date
        if lock_date is None:
            return False
        from django.utils import timezone as _tz
        return _tz.now() > lock_date

    @property
    def percentage(self):
        try:
            return round((float(self.marks) / float(self.exam.max_marks)) * 100, 1)
        except (ZeroDivisionError, TypeError):
            return 0

    @property
    def grade_band(self):
        from .grading import band_for
        return band_for(self.percentage, getattr(self.exam, 'date', None))

    @property
    def letter_grade(self):
        return self.grade_band.grade

    @property
    def grade_point(self):
        return self.grade_band.grade_point

    @property
    def status(self):
        return 'pass' if self.grade_band.is_pass else 'fail'

    @property
    def is_published(self):
        if not self.registration_id:
            return False
        pub = getattr(self.registration, 'result_publication', None)
        return bool(pub and pub.status == 'published')

    @property
    def can_apply_retake(self):
        return not self.grade_band.is_pass

    @property
    def can_apply_improvement(self):
        b = self.grade_band
        return b.is_pass and b.allows_improvement

    @property
    def result_label(self):
        if self.status == 'fail':
            return 'Fail'
        if self.attempt_type == 'improvement':
            return f'Improvement ({self.letter_grade})'
        if self.attempt_type == 'retake':
            return f'Retake Pass ({self.letter_grade})'
        return f'Regular Pass ({self.letter_grade})'

    class Meta:
        verbose_name = 'Grade Entry'
        verbose_name_plural = 'Grade Entries'


def best_attempt_per_course(entries):
    """Further collapses already-canonical (one-per-semester) grade entries
    to ONE per (student, course) across ALL semesters - the LATEST attempt
    wins. This is the retake/improvement CGPA policy: a later attempt
    replaces an earlier one for cumulative GPA purposes, so a failed course
    that was later retaken and passed contributes its PASSING grade to CGPA
    exactly once, not both the original failing credits and the new ones.

    This is used only for CGPA/standing/remaining-credits - per-semester GPA
    (what the transcript shows for e.g. "Fall 2025") is computed separately
    from the untouched canonical_grades() result, so the original attempt's
    grade still correctly appears in ITS OWN semester's history."""
    best = {}
    for e in entries:
        key = (e.student_id, e.exam.course_id)
        current = best.get(key)
        if current is None or e.entered_at > current.entered_at:
            best[key] = e
    return list(best.values())


def canonical_grades(grades):
    """Collapse a list/queryset of GradeEntry to ONE entry per
    (student, course, semester).

    Real bug this fixes: a course is only meant to have a single result
    per student per semester, but nothing ever stopped two separate
    ExamSession rows being created for the same course/semester (e.g.
    "CS101 Midterm" and "Semester exam CS101" both existing side by
    side, each with its own full component breakdown). Every place that
    summed grade_point*credits for GPA/CGPA, or counted retake/
    improvement opportunities, was iterating raw GradeEntry rows - so a
    duplicated course silently counted its credits twice toward CGPA and
    showed as two separate retake opportunities instead of one.

    The most recently entered row per (student, course, semester) is
    treated as the authoritative one (a later save is normally a
    correction). This does not delete or touch the extra rows - it only
    changes what GPA/CGPA/retake-counting code looks at - so nothing
    already on disk needs to change for this to take effect.
    """
    best = {}
    for g in grades:
        key = (g.student_id, g.exam.course_id, g.exam.semester_id)
        current = best.get(key)
        if current is None or g.entered_at > current.entered_at:
            best[key] = g
    return list(best.values())


class RetakeApplication(models.Model):
    """Student applies to either retake a failed exam, or sit an improvement
    exam for one they already passed. Approval generates a fee challan."""
    APPLICATION_TYPE_CHOICES = [
        ('improvement', 'Improvement (already passed, want a better grade)'),
        ('retake', 'Retake (failed - need to pass)'),
    ]
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('completed', 'Completed')]

    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='retake_applications')
    grade_entry = models.ForeignKey(GradeEntry, on_delete=models.CASCADE, related_name='retake_applications')
    application_type = models.CharField(max_length=20, choices=APPLICATION_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(auto_now_add=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-applied_at']

    def __str__(self):
        return f'{self.student.full_name} - {self.grade_entry.exam.course.code} ({self.get_application_type_display()})'

    @property
    def linked_invoice(self):
        """The fee challan generated when this application was approved, if any."""
        from finance.models import Invoice
        course = self.grade_entry.exam.course
        return Invoice.objects.filter(
            student=self.student, category='exam_retake',
            reference__icontains=course.code,
        ).order_by('-created_at').first()

    @property
    def exam_eligibility_status(self):
        """Human-readable eligibility: student can only sit the retake/
        improvement exam once the challan is paid AND staff have approved."""
        if self.status == 'rejected':
            return 'Not eligible - application rejected'
        invoice = self.linked_invoice
        if invoice and not invoice.paid:
            return 'Pay the fee challan first'
        if self.status == 'pending':
            return 'Fee paid - awaiting staff approval'
        if self.status == 'approved':
            return 'Eligible to sit the exam'
        return self.get_status_display()


class AssessmentScheme(models.Model):
    """Versioned assessment definition for a course/section.

    This replaces the conceptual four-fixed-component limitation without
    breaking legacy GradeEntry data. New assessments can contain any number
    of components (quiz, assignment, lab, midterm, project, viva, final,
    practical, attendance, etc.).
    """
    course = models.ForeignKey('academics.Course', on_delete=models.CASCADE, related_name='assessment_schemes')
    name = models.CharField(max_length=150, default='Standard Assessment Scheme')
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'version'], name='uniq_assessment_scheme_version')]
        ordering = ['course', '-version']

    @property
    def weight_total(self):
        if not self.pk:
            return Decimal('0')
        return sum((c.weight for c in self.components.all()), Decimal('0'))

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk and self.weight_total != Decimal('100'):
            raise ValidationError('Assessment component weights must total 100%.')

    def __str__(self):
        return f'{self.course.code} — {self.name} v{self.version}'


class AssessmentComponent(models.Model):
    COMPONENT_CHOICES = [
        ('attendance', 'Attendance'), ('quiz', 'Quiz'), ('assignment', 'Assignment'),
        ('lab', 'Lab'), ('midterm', 'Midterm'), ('project', 'Project'),
        ('viva', 'Viva'), ('presentation', 'Presentation'), ('practical', 'Practical'),
        ('final', 'Final Exam'), ('other', 'Other'),
    ]
    scheme = models.ForeignKey(AssessmentScheme, on_delete=models.CASCADE, related_name='components')
    name = models.CharField(max_length=100)
    component_type = models.CharField(max_length=30, choices=COMPONENT_CHOICES, default='other')
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    max_marks = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    order = models.PositiveSmallIntegerField(default=1)
    is_required = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [models.UniqueConstraint(fields=['scheme', 'name'], name='uniq_assessment_component_name')]

    def __str__(self):
        return f'{self.scheme.course.code} — {self.name} ({self.weight}%)'


class AssessmentMark(models.Model):
    """Raw mark entered by a teacher for one registered student/component."""
    registration = models.ForeignKey('academics.CourseRegistration', on_delete=models.CASCADE, related_name='assessment_marks')
    component = models.ForeignKey(AssessmentComponent, on_delete=models.CASCADE, related_name='marks')
    raw_marks = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    entered_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    entered_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['registration', 'component'], name='uniq_registration_component_mark')]
        indexes = [models.Index(fields=['registration', 'component'])]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.raw_marks is not None and self.raw_marks < 0:
            raise ValidationError('Raw marks cannot be negative.')
        if self.raw_marks is not None and self.component_id and self.raw_marks > self.component.max_marks:
            raise ValidationError(f'Raw marks cannot exceed {self.component.max_marks}.')
        if self.registration_id and self.component_id:
            if self.registration.section.course_id != self.component.scheme.course_id:
                raise ValidationError('Assessment component does not belong to the registered course.')

    @property
    def weighted_marks(self):
        if self.raw_marks is None or not self.component.max_marks:
            return Decimal('0')
        return (self.raw_marks / self.component.max_marks * self.component.weight).quantize(Decimal('0.01'))


class ResultPublication(models.Model):
    STATUS_CHOICES = [('teacher_submitted','Teacher Submitted'), ('department_verified','Department Verified'), ('exam_verified','Exam Office Verified'), ('published','Published'), ('reopened','Reopened')]
    registration = models.OneToOneField('academics.CourseRegistration', on_delete=models.CASCADE, related_name='result_publication')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='teacher_submitted')
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f'{self.registration} — {self.get_status_display()}'


class GradeScale(models.Model):
    name = models.CharField(max_length=100)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from', '-id']

    def __str__(self):
        return f'{self.name} (from {self.effective_from})'


class GradeBand(models.Model):
    scale = models.ForeignKey(GradeScale, on_delete=models.CASCADE, related_name='bands')
    grade = models.CharField(max_length=5)
    min_percent = models.DecimalField(max_digits=5, decimal_places=2)
    max_percent = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    grade_point = models.DecimalField(max_digits=4, decimal_places=2)
    is_pass = models.BooleanField(default=True)
    allows_improvement = models.BooleanField(default=False)

    class Meta:
        ordering = ['-min_percent']
        unique_together = [('scale', 'grade')]

    def __str__(self):
        return f'{self.grade} >= {self.min_percent}%'


class ResultVersion(models.Model):
    """Snapshot of a grade entry taken BEFORE every change - no silent overwrite."""
    grade_entry = models.ForeignKey(GradeEntry, on_delete=models.CASCADE, related_name='versions')
    marks = models.DecimalField(max_digits=6, decimal_places=2)
    grade = models.CharField(max_length=10, blank=True)
    components = models.JSONField(default=dict, blank=True)
    changed_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class ResultChangeRequest(models.Model):
    """A teacher's request to change a locked/published result; nothing
    changes until an authorised officer approves."""
    STATUS = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    COMPONENT_FIELDS = ['attendance_marks', 'assignment_marks', 'midterm_marks', 'final_marks']
    grade_entry = models.ForeignKey(GradeEntry, on_delete=models.CASCADE, related_name='change_requests')
    requested_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, related_name='result_change_requests')
    reason = models.TextField()
    new_attendance_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    new_assignment_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    new_midterm_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    new_final_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    old_marks = models.DecimalField(max_digits=6, decimal_places=2)
    old_grade = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    reviewed_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def proposed_components(self):
        return {f: getattr(self, 'new_' + f) for f in self.COMPONENT_FIELDS if getattr(self, 'new_' + f) is not None}


def _clear_grade_cache(sender, **kwargs):
    from .grading import clear_cache
    clear_cache()


from django.db.models.signals import post_delete, post_save  # noqa: E402

for _m in (GradeScale, GradeBand):
    post_save.connect(_clear_grade_cache, sender=_m)
    post_delete.connect(_clear_grade_cache, sender=_m)
