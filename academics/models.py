import datetime
from django.db import models
from django.utils import timezone

class Faculty(models.Model):
    name = models.CharField(max_length=200)
    dean = models.CharField(max_length=200, blank=True)
    def __str__(self): return self.name
    class Meta:
        verbose_name_plural = 'Faculties'

class Department(models.Model):
    name = models.CharField(max_length=200)
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name='departments')
    head_of_department = models.CharField(max_length=150, blank=True, verbose_name='Head of Department')
    established_year = models.IntegerField(null=True, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    building = models.CharField(max_length=150, blank=True, help_text='Building or block where this department is located')
    def __str__(self): return self.name

class Program(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True)
    LEVEL_CHOICES = [
        ('bachelor', "Bachelor's (BS/BSc)"),
        ('master', "Master's (MS/MSc)"),
        ('mphil', 'MPhil'),
        ('phd', 'PhD'),
    ]
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='bachelor')
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='programs')
    duration_years = models.IntegerField(default=3)
    semester_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=45000,
        help_text='Per-semester tuition fee for this program - used by student self-service fee-challan generation.',
    )
    application_fee = models.DecimalField(max_digits=10, decimal_places=2, default=3000, help_text='One-time application/processing fee for this program, charged when an applicant applies (0 = free).')
    admission_fee = models.DecimalField(max_digits=10, decimal_places=2, default=25000, help_text='One-time admission fee for this program, charged automatically when the applicant is admitted (0 = none).')
    degree_fee = models.DecimalField(max_digits=10, decimal_places=2, default=10000, help_text='One-time degree/convocation fee for this program, charged automatically to a graduating student (0 = none).')
    open_merit_seats = models.PositiveSmallIntegerField(default=30, help_text='Seats available under open merit for this program, per admission cycle.')
    district_quota_seats = models.PositiveSmallIntegerField(default=10, help_text='Seats reserved for the district-quota admission pathway for this program, per admission cycle.')
    def __str__(self): return f"{self.name} ({self.code})"

class AcademicSession(models.Model):
    year = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    def __str__(self): return self.year

class Semester(models.Model):
    name = models.CharField(max_length=100)
    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    # 1st-10th semester (covers everything from a typical 4-year/8-semester
    # BS degree up to 5-year professional programs like Pharm-D/Engineering
    # that run 10 semesters); odd = Fall, even = Spring.
    semester_number = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='1st-10th semester of the program (odd = Fall, even = Spring).',
    )
    registration_open = models.DateTimeField(null=True, blank=True, help_text='Course selection opens. Blank = open from the first day of the semester.')
    registration_close = models.DateTimeField(null=True, blank=True, help_text='Course selection closes. After this students cannot register for new courses.')
    drop_deadline = models.DateTimeField(null=True, blank=True, help_text='Last moment a student may drop a course. Blank = same as the registration close; if that is blank too, the default drop window from Site Settings applies.')
    exam_registration_open = models.DateTimeField(null=True, blank=True)
    exam_registration_close = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.display_name

    # ---- Registration / drop / exam-registration windows ------------------
    # One place that decides "is this action allowed right now" so course
    # selection, dropping, auto-assignment, retake/exam registration and the
    # UI banners can never disagree with each other.

    @staticmethod
    def _window(opens, closes, now):
        if opens and now < opens:
            return 'not_open'
        if closes and now > closes:
            return 'closed'
        return 'open'

    def registration_state(self, now=None):
        """'not_open' | 'open' | 'closed' for adding courses."""
        return self._window(self.registration_open, self.registration_close, now or timezone.now())

    @property
    def effective_drop_deadline(self):
        """Explicit drop deadline, else the registration close, else the
        Site Settings default (N days after the semester starts, end of that
        day in local time). Never None, so a drop can never be silently
        unlimited just because an administrator forgot to set a date."""
        if self.drop_deadline:
            return self.drop_deadline
        if self.registration_close:
            return self.registration_close
        from core.models import SiteSettings
        days = SiteSettings.load().default_drop_window_days
        last_day = self.start_date + datetime.timedelta(days=days)
        return timezone.make_aware(datetime.datetime.combine(last_day, datetime.time(23, 59, 59)))

    def drop_state(self, now=None):
        """'open' while a drop is still allowed, else 'closed'. A drop is also
        not allowed before the semester starts (nothing to drop yet)."""
        now = now or timezone.now()
        return 'open' if now <= self.effective_drop_deadline else 'closed'

    def exam_registration_state(self, now=None):
        """'not_configured' when no exam-registration dates are set (so the
        UI can say so honestly), else 'not_open' | 'open' | 'closed'."""
        if not self.exam_registration_open and not self.exam_registration_close:
            return 'not_configured'
        return self._window(self.exam_registration_open, self.exam_registration_close, now or timezone.now())

    @property
    def display_name(self):
        """Human-facing label that never shows the session year twice.
        A name may already contain the session year (e.g. "Fall 2026 -
        2026-2027") or be bare (e.g. "Fall 2026"); the year is appended only
        when it is not already there."""
        year = str(self.session.year) if self.session_id else ''
        if year and year in self.name:
            return self.name
        return f"{self.name} — {year}" if year else self.name

    @property
    def term_type(self):
        if not self.semester_number:
            return ''
        return 'Fall' if self.semester_number % 2 == 1 else 'Spring'

class Course(models.Model):
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    credits = models.IntegerField(default=3)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='courses')
    prerequisites = models.ManyToManyField('self', blank=True, symmetrical=False)
    syllabus = models.TextField(blank=True)

    # Configurable assessment scheme - each weight is both the % of the
    # final grade AND the raw-marks ceiling for that component (see
    # GradeEntry.save() and GradeEntryForm.clean() - a teacher enters raw
    # marks for each component up to its own weight here, e.g. "8" for an
    # attendance component with weight=10).
    attendance_weight = models.PositiveSmallIntegerField(default=10, help_text='% of final grade from the attendance component.')
    assignment_weight = models.PositiveSmallIntegerField(default=20, help_text='% of final grade from the assignment component.')
    midterm_weight = models.PositiveSmallIntegerField(default=30, help_text='% of final grade from the midterm component.')
    final_weight = models.PositiveSmallIntegerField(default=40, help_text='% of final grade from the final exam component.')

    def clean(self):
        from django.core.exceptions import ValidationError
        total = self.attendance_weight + self.assignment_weight + self.midterm_weight + self.final_weight
        if total != 100:
            raise ValidationError(f'Assessment weights must add up to 100% (currently {total}%).')

    def __str__(self): return f"{self.code} - {self.name}"

class Curriculum(models.Model):
    """Authoritative degree curriculum for automatic academic progression.

    A program may have multiple curriculum versions; only one should be active
    for a student's admission cohort. Course assignment is derived from the
    curriculum instead of manually attaching arbitrary courses to students.
    """
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='curricula')
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=40, default='2026')
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    total_credits = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['program', '-version']
        constraints = [
            models.UniqueConstraint(fields=['program', 'version'], name='uniq_curriculum_program_version'),
        ]

    def __str__(self):
        return f'{self.program.code or self.program.name} — {self.name} v{self.version}'


class CurriculumSemester(models.Model):
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name='semesters')
    semester_number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120, blank=True)
    credits_required = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['curriculum', 'semester_number']
        constraints = [
            models.UniqueConstraint(fields=['curriculum', 'semester_number'], name='uniq_curriculum_semester_number'),
        ]

    @property
    def year_number(self):
        return (self.semester_number + 1) // 2

    def __str__(self):
        return self.title or f'Year {self.year_number} — Semester {self.semester_number}'


class CurriculumCourse(models.Model):
    curriculum_semester = models.ForeignKey(CurriculumSemester, on_delete=models.CASCADE, related_name='courses')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='curriculum_entries')
    COURSE_TYPE_CHOICES = [('required', 'Required'), ('elective', 'Elective')]
    course_type = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, default='required')
    elective_group = models.CharField(max_length=100, blank=True)
    recommended = models.BooleanField(default=True)
    minimum_grade = models.CharField(max_length=5, blank=True)

    class Meta:
        ordering = ['curriculum_semester__semester_number', 'course__code']
        constraints = [
            models.UniqueConstraint(fields=['curriculum_semester', 'course'], name='uniq_curriculum_course'),
        ]

    def __str__(self):
        return f'{self.curriculum_semester} — {self.course.code} ({self.course_type})'


class CourseSection(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='sections')
    code = models.CharField(max_length=64)
    instructor = models.ForeignKey('hr.Staff', null=True, blank=True, on_delete=models.SET_NULL)
    capacity = models.IntegerField(default=30)
    section_type = models.CharField(max_length=10, choices=[('lec','Lecture'),('lab','Lab'),('tut','Tutorial')], default='lec')
    schedule_notes = models.TextField(blank=True)

    @property
    def seats_taken(self):
        return self.registrations.filter(status='registered').count()

    @property
    def seats_available(self):
        return max(0, self.capacity - self.seats_taken)

    def seats_taken_in(self, semester):
        """Seats used in ONE institutional semester - a section is reused
        every term, so last term's registrations must not consume this
        term's capacity."""
        qs = self.registrations.filter(status='registered')
        return qs.filter(semester=semester).count() if semester else qs.count()

    def seats_available_in(self, semester):
        return max(0, self.capacity - self.seats_taken_in(semester))

    def __str__(self):
        return f'{self.course.code}-{self.code}'

    class Meta:
        verbose_name = 'Course Section'
        verbose_name_plural = 'Course Sections'


class CourseRegistration(models.Model):
    """Self-service course registration: a student enrolls themselves into a
    course section for a given semester, capped by the section's capacity."""
    STATUS_CHOICES = [('registered', 'Registered'), ('dropped', 'Dropped')]
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='course_registrations')
    section = models.ForeignKey(CourseSection, on_delete=models.CASCADE, related_name='registrations')
    semester = models.ForeignKey(Semester, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='registered')
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-registered_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'section', 'semester'],
                condition=models.Q(status='registered'),
                name='uniq_active_course_registration',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['section', 'status']),
        ]

    def __str__(self):
        return f'{self.student.full_name} - {self.section} ({self.get_status_display()})'