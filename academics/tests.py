"""
Tests for academics: self-service course registration and prerequisite
enforcement.

These tests are intentionally date-independent. They create an active
academic semester relative to the current date so registration tests do not
break when the calendar year changes.

Run with:
    python manage.py test academics --verbosity=2
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from academics.models import (
    AcademicSession,
    Course,
    CourseSection,
    Department,
    Faculty,
    Program,
    Semester,
)
from exams.models import ExamSession, GradeEntry
from registration.models import Student


class PrerequisiteEnforcementTests(TestCase):
    """
    Verify that:

    1. A course without prerequisites can be registered.
    2. A course can be registered after its prerequisite is passed.
    3. A course cannot be registered when its prerequisite is not passed.
    """

    def setUp(self):
        # ---------------------------------------------------------------
        # Academic structure
        # ---------------------------------------------------------------
        faculty = Faculty.objects.create(
            name="Faculty of Engineering"
        )

        dept = Department.objects.create(
            name="Computer Science",
            faculty=faculty,
        )

        self.program = Program.objects.create(
            name="BS Computer Science",
            code="CS",
            department=dept,
        )

        # ---------------------------------------------------------------
        # Courses
        # ---------------------------------------------------------------
        self.intro_course = Course.objects.create(
            code="CS101",
            name="Intro to Programming",
            credits=3,
            program=self.program,
        )

        self.advanced_course = Course.objects.create(
            code="CS201",
            name="Data Structures",
            credits=3,
            program=self.program,
        )

        # CS201 requires CS101.
        self.advanced_course.prerequisites.add(
            self.intro_course
        )

        # ---------------------------------------------------------------
        # Course section
        # ---------------------------------------------------------------
        self.section = CourseSection.objects.create(
            course=self.advanced_course,
            code="A",
            capacity=30,
        )

        # ---------------------------------------------------------------
        # Student
        # ---------------------------------------------------------------
        user = User.objects.create_user(
            username="prereqstudent",
            password="p",
        )

        self.student = Student.objects.create(
            user=user,
            full_name="Prereq Student",
            admission_no="UMS-P-001",
            program=self.program,
        )

        # ---------------------------------------------------------------
        # IMPORTANT:
        #
        # AcademicEligibilityService.current_semester() only returns a
        # semester whose dates contain today's date.
        #
        # The old tests used 2025-2026, which is already expired.
        # Create a dynamic active semester instead.
        # ---------------------------------------------------------------
        today = timezone.localdate()

        self.session = AcademicSession.objects.create(
            year=f"{today.year}-{today.year + 1}",
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=300),
        )

        self.semester = Semester.objects.create(
            session=self.session,
            name="Semester 1",
            semester_number=1,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=120),
        )

    # -------------------------------------------------------------------
    # TEST 1
    # -------------------------------------------------------------------
    def test_registration_blocked_without_prerequisite(self):
        """
        A student must not be able to register for a course when the
        required prerequisite has not been passed.
        """
        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse(
                "register-section",
                args=[self.section.id],
            )
        )

        # The view redirects after displaying the validation message.
        self.assertEqual(response.status_code, 302)

        # The advanced course must NOT have been registered.
        self.assertFalse(
            self.student.course_registrations.filter(
                status="registered",
                section=self.section,
            ).exists()
        )

    # -------------------------------------------------------------------
    # TEST 2
    # -------------------------------------------------------------------
    def test_registration_allowed_after_passing_prerequisite(self):
        """
        A student who has passed the prerequisite course should be
        allowed to register for the advanced course.
        """

        # Create an exam for CS101 in the active semester.
        exam = ExamSession.objects.create(
            name="Final",
            course=self.intro_course,
            semester=self.semester,
            date=self.semester.start_date + timedelta(days=60),
            max_marks=100,
        )

        # Create a passing grade.
        GradeEntry.objects.create(
            student=self.student,
            exam=exam,
            marks=85,
        )

        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse(
                "register-section",
                args=[self.section.id],
            )
        )

        # Successful registration redirects to my registrations.
        self.assertEqual(response.status_code, 302)

        # The advanced course must now be registered.
        self.assertTrue(
            self.student.course_registrations.filter(
                status="registered",
                section=self.section,
                semester=self.semester,
            ).exists()
        )

    # -------------------------------------------------------------------
    # TEST 3
    # -------------------------------------------------------------------
    def test_course_without_prerequisites_registers_freely(self):
        """
        A course without prerequisites should be available for
        registration when the student otherwise satisfies eligibility.
        """

        intro_section = CourseSection.objects.create(
            course=self.intro_course,
            code="A",
            capacity=30,
        )

        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse(
                "register-section",
                args=[intro_section.id],
            )
        )

        # Successful registration redirects.
        self.assertEqual(response.status_code, 302)

        # The course must actually be registered.
        self.assertTrue(
            self.student.course_registrations.filter(
                status="registered",
                section=intro_section,
                semester=self.semester,
            ).exists()
        )


class ScheduleConflictTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        today = timezone.localdate()
        session = AcademicSession.objects.create(year='Test Session', start_date=today - timedelta(days=30), end_date=today + timedelta(days=100))
        self.semester = Semester.objects.create(session=session, name='Test Semester', semester_number=1, start_date=today - timedelta(days=10), end_date=today + timedelta(days=80))

        course_a = Course.objects.create(code='CS101', name='Course A', credits=3, program=self.program)
        course_b = Course.objects.create(code='CS102', name='Course B', credits=3, program=self.program)
        self.section_a = CourseSection.objects.create(course=course_a, code='A', capacity=30)
        self.section_b = CourseSection.objects.create(course=course_b, code='A', capacity=30)

        user = User.objects.create_user(username='conflictstudent', password='p')
        self.student = Student.objects.create(user=user, full_name='Conflict Student', admission_no='UMS-CONFLICT-001', program=self.program)

        from timetable.models import Room, TimeSlot, TimetableAssignment
        self.room = Room.objects.create(name='Room 1', capacity=50)
        self.slot_mon_9 = TimeSlot.objects.create(day='mon', start_time='09:00', end_time='10:30')
        TimetableAssignment.objects.create(section=self.section_a, room=self.room, timeslot=self.slot_mon_9, semester=self.semester)

    def test_overlapping_schedule_is_rejected(self):
        from timetable.models import TimeSlot, TimetableAssignment
        overlapping_slot = TimeSlot.objects.create(day='mon', start_time='10:00', end_time='11:30')
        TimetableAssignment.objects.create(section=self.section_b, room=self.room, timeslot=overlapping_slot, semester=self.semester)

        self.client.force_login(self.student.user)
        self.client.post(reverse('register-section', args=[self.section_a.id]))
        response = self.client.post(reverse('register-section', args=[self.section_b.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.student.course_registrations.filter(section=self.section_b, status='registered').exists())

    def test_non_overlapping_schedule_is_allowed(self):
        from timetable.models import TimeSlot, TimetableAssignment
        clear_slot = TimeSlot.objects.create(day='tue', start_time='09:00', end_time='10:30')
        TimetableAssignment.objects.create(section=self.section_b, room=self.room, timeslot=clear_slot, semester=self.semester)

        self.client.force_login(self.student.user)
        self.client.post(reverse('register-section', args=[self.section_a.id]))
        response = self.client.post(reverse('register-section', args=[self.section_b.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.student.course_registrations.filter(section=self.section_b, status='registered').exists())

    def test_section_without_timetable_never_blocks(self):
        """No schedule published yet = nothing to conflict with."""
        self.client.force_login(self.student.user)
        self.client.post(reverse('register-section', args=[self.section_a.id]))
        response = self.client.post(reverse('register-section', args=[self.section_b.id]))
        self.assertTrue(self.student.course_registrations.filter(section=self.section_b, status='registered').exists())


class CourseRegistrationAdminTests(TestCase):
    """Admin-created registrations must go through the same eligibility
    service as a student's own registration - not a raw insert that
    bypasses prerequisites/credit-limits/capacity."""

    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BS Computer Science', code='CS', department=dept)
        today = timezone.localdate()
        session = AcademicSession.objects.create(year='Test Session', start_date=today - timedelta(days=30), end_date=today + timedelta(days=100))
        self.semester = Semester.objects.create(session=session, name='Test Semester', semester_number=1, start_date=today - timedelta(days=10), end_date=today + timedelta(days=80))
        self.intro = Course.objects.create(code='CS101', name='Intro', credits=3, program=self.program)
        self.advanced = Course.objects.create(code='CS201', name='Advanced', credits=3, program=self.program)
        self.advanced.prerequisites.add(self.intro)
        self.section = CourseSection.objects.create(course=self.advanced, code='A', capacity=30)
        user = User.objects.create_user(username='adminregstudent', password='p')
        self.student = Student.objects.create(user=user, full_name='Admin Reg Student', admission_no='UMS-ADMINREG-001', program=self.program)
        self.admin = User.objects.create_superuser(username='adminregadmin', password='p', email='a@example.com')

    def test_admin_cannot_bypass_prerequisite_via_admin_panel(self):
        from academics.models import CourseRegistration
        self.client.force_login(self.admin)
        response = self.client.post('/admin/academics/courseregistration/add/', {
            'student': self.student.pk, 'section': self.section.pk, 'semester': self.semester.pk, 'status': 'registered',
        })
        # Rejected with a normal form re-render (200 + inline error), not a 500.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Prerequisites not satisfied')
        self.assertFalse(CourseRegistration.objects.filter(student=self.student, section=self.section, status='registered').exists())

    def test_admin_can_create_eligible_registration(self):
        from academics.models import CourseRegistration
        # Give the student the prerequisite first.
        from exams.models import ExamSession, GradeEntry
        exam = ExamSession.objects.create(name='Final', course=self.intro, semester=self.semester, date=timezone.localdate(), max_marks=100)
        GradeEntry.objects.create(student=self.student, exam=exam, marks=80)
        self.client.force_login(self.admin)
        response = self.client.post('/admin/academics/courseregistration/add/', {
            'student': self.student.pk, 'section': self.section.pk, 'semester': self.semester.pk, 'status': 'registered',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CourseRegistration.objects.filter(student=self.student, section=self.section, status='registered').exists())


class FacultyProgramSectionManagementViewsTests(TestCase):
    """Faculties, Programs, and Course Sections each need their own real
    human-facing list/add/edit pages - not just Django admin or the raw
    DRF API - matching the pattern already established by Courses and
    Departments."""

    def setUp(self):
        # a Super Administrator (superuser). Plain is_staff is NOT admin.
        self.admin = User.objects.create_user('mgmt_admin', password='pw', is_staff=True, is_superuser=True)
        self.plain_staff = User.objects.create_user('mgmt_plain_staff', password='pw', is_staff=True)
        self.student_user = User.objects.create_user('mgmt_student', password='pw')
        faculty = Faculty.objects.create(name='Engineering & CS')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.course = Course.objects.create(code='CS201', name='Data Structures', credits=3, program=self.program)
        self.section = CourseSection.objects.create(course=self.course, code='A', capacity=30)
        self.faculty = faculty
        self.dept = dept

    def test_faculty_list_loads_for_any_logged_in_user(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('faculty-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Engineering &amp; CS')

    def test_faculty_add_requires_admin(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('faculty-add'))
        self.assertEqual(resp.status_code, 403)

    def test_plain_staff_without_grants_cannot_add_faculty_or_edit_program(self):
        # Rule: is_staff alone never grants institutional configuration.
        self.client.force_login(self.plain_staff)
        self.assertEqual(self.client.get(reverse('faculty-add')).status_code, 403)
        resp = self.client.post(reverse('program-edit', args=[self.program.pk]), {'name': 'Hacked', 'code': 'BSCS'})
        self.assertEqual(resp.status_code, 403)
        self.program.refresh_from_db()
        self.assertEqual(self.program.name, 'BSCS')

    def test_admin_can_add_faculty(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('faculty-add'), {'name': 'Faculty of Business', 'dean': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Faculty.objects.filter(name='Faculty of Business').exists())

    def test_program_list_shows_seeded_program(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('program-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'BSCS')

    def test_admin_can_edit_program(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('program-edit', args=[self.program.pk]), {
            'name': 'BS Computer Science', 'code': 'BSCS', 'level': 'bachelor',
            'department': self.dept.pk, 'duration_years': 4,
            'semester_fee': '50000', 'application_fee': '3500', 'admission_fee': '28000',
            'degree_fee': '12000', 'open_merit_seats': 30, 'district_quota_seats': 10,
        })
        self.assertEqual(resp.status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.name, 'BS Computer Science')
        # fees are per program, so each one must persist independently.
        self.assertEqual(int(self.program.application_fee), 3500)
        self.assertEqual(int(self.program.admission_fee), 28000)
        self.assertEqual(int(self.program.degree_fee), 12000)

    def test_section_list_shows_seeded_section_with_live_seat_counts(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('section-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'CS201')
        self.assertContains(resp, 'Unassigned')  # no instructor set yet

    def test_section_add_requires_staff_or_admin(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(reverse('section-add'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_add_section(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('section-add'), {
            'course': self.course.pk, 'code': 'B', 'capacity': 25,
            'section_type': 'lec', 'schedule_notes': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CourseSection.objects.filter(course=self.course, code='B').exists())

    def test_course_list_shows_section_count(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('course-list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'CS201')


class BrowseSectionsCreditsSemesterScopingTests(TestCase):
    """Regression test for a real reported bug: the Course Selection page
    showed sections as "Registered" (checked regardless of which semester
    the registration belonged to) while "Credit hours registered" showed
    0/21 for that same section - because the credit sum WAS correctly
    scoped to the semester being viewed, but the "Registered" checkmark
    set was not scoped at all. Both must agree with each other."""

    def setUp(self):
        from academics.models import CourseRegistration
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        self.section = CourseSection.objects.create(course=course, code='A', capacity=40)

        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date() - timedelta(days=10), end_date=timezone.now().date() + timedelta(days=300))
        self.registered_semester = Semester.objects.create(
            name='Fall 2026', session=session,
            start_date=timezone.now().date() - timedelta(days=10), end_date=timezone.now().date() + timedelta(days=150),
        )
        other_session = AcademicSession.objects.create(year='2029-2030', start_date=timezone.now().date() + timedelta(days=400), end_date=timezone.now().date() + timedelta(days=700))
        self.other_semester = Semester.objects.create(
            name='Semester 9', session=other_session,
            start_date=timezone.now().date() + timedelta(days=400), end_date=timezone.now().date() + timedelta(days=550),
        )

        user = User.objects.create_user('scopingtest_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Scoping Test', admission_no='SCT-001', program=program, status='active')
        CourseRegistration.objects.create(student=self.student, section=self.section, semester=self.registered_semester, status='registered')

    def test_registered_flag_and_credits_agree_when_viewing_the_right_semester(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('browse-sections'), {'semester': self.registered_semester.pk})
        self.assertIn(self.section.id, resp.context['my_section_ids'])
        self.assertEqual(resp.context['credits_registered'], 3)

    def test_registered_flag_and_credits_agree_when_viewing_a_different_semester(self):
        self.client.force_login(self.student.user)
        resp = self.client.get(reverse('browse-sections'), {'semester': self.other_semester.pk})
        self.assertNotIn(self.section.id, resp.context['my_section_ids'])
        self.assertEqual(resp.context['credits_registered'], 0)


class BrowseSectionsSlicedQuerysetBugTests(TestCase):
    """Regression test for a real, more serious bug the scoping tests
    above surfaced: viewing a specific semester (the "13th newest" or
    older, i.e. outside the dropdown's default top-12-by-date slice)
    crashed with 'Cannot filter a query once a slice has been taken',
    silently caught by a broad except and shown to the student as "No
    sections are currently eligible for you to register for in this
    semester" - which looked like a data problem but was actually a code
    bug reachable on every semester outside the most-recent 12."""

    def setUp(self):
        from academics.models import CourseRegistration
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        self.program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        self.course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=self.program)
        self.section = CourseSection.objects.create(course=self.course, code='A', capacity=40)

        # Create 15 semesters with descending start dates so the target
        # semester (the oldest, #15) falls outside any top-12 slice.
        base = timezone.now().date()
        self.old_semester = None
        for i in range(15):
            session = AcademicSession.objects.create(
                year=f'OLDYR{i}', start_date=base - timedelta(days=(i + 1) * 400), end_date=base - timedelta(days=i * 400),
            )
            sem = Semester.objects.create(
                name=f'Old Semester {i}', session=session,
                start_date=base - timedelta(days=(i + 1) * 400), end_date=base - timedelta(days=i * 400),
            )
            if i == 14:
                self.old_semester = sem

        user = User.objects.create_user('slicedbug_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Sliced Bug Test', admission_no='SLB-001', program=self.program, status='active')

    def test_viewing_a_semester_outside_the_dropdown_slice_does_not_crash(self):
        """The real assertion here isn't about registration eligibility
        (an ancient closed semester correctly has no open registration
        window - that's a legitimate business rule, not a bug). The point
        is that resolving `?semester=<old id>` must not raise, and must
        not silently fall into the generic exception handler that used to
        wipe out the section list and log nothing."""
        import logging

        self.client.force_login(self.student.user)
        logger = logging.getLogger('ums.errors')
        handler = logging.Handler()
        records = []
        handler.emit = records.append
        logger.addHandler(handler)
        try:
            resp = self.client.get(reverse('browse-sections'), {'semester': self.old_semester.pk})
        finally:
            logger.removeHandler(handler)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(records, [])  # no unexpected exception was caught/logged
        self.assertEqual(resp.context['viewing_semester'], self.old_semester)


class SemesterDisplayNameDuplicationBugTests(TestCase):
    """Regression test for a real reported bug: a semester dropdown
    showed "Fall 2026 - 2026-2027 — 2026-2027" - the session year
    appearing twice - because some semesters were seeded with the year
    already baked into `name` while the display code unconditionally
    appended "- {session.year}" on top."""

    def test_year_not_duplicated_when_already_in_name(self):
        session = AcademicSession.objects.create(year='2026-2027', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        sem = Semester.objects.create(name='Fall 2026 - 2026-2027', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        self.assertEqual(str(sem), 'Fall 2026 - 2026-2027')
        self.assertEqual(sem.display_name, 'Fall 2026 - 2026-2027')

    def test_year_appended_when_name_is_bare(self):
        session = AcademicSession.objects.create(year='2027-2028', start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=300))
        sem = Semester.objects.create(name='Fall 2027', session=session, start_date=timezone.now().date(), end_date=timezone.now().date() + timedelta(days=150))
        self.assertEqual(str(sem), 'Fall 2027 — 2027-2028')


class DuplicateRegistrationAcrossOverlappingSemestersTests(TestCase):
    """Regression test for a real reported bug: a student ended up with
    TWO active registrations for the same course/section - each under a
    different Semester row that both represented the same real "Fall
    2026" term (created by separate seed runs with slightly different
    names/dates, so a plain semester=semester check never caught it).
    """

    def setUp(self):
        from academics.models import CourseRegistration
        faculty = Faculty.objects.create(name='Faculty of Engineering')
        dept = Department.objects.create(name='Computer Science', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        course = Course.objects.create(code='CS101', name='Programming Fundamentals', credits=3, program=program)
        self.section = CourseSection.objects.create(course=course, code='A', capacity=40)

        base = timezone.now().date()
        session1 = AcademicSession.objects.create(year='2026-2027', start_date=base - timedelta(days=5), end_date=base + timedelta(days=300))
        self.sem_a = Semester.objects.create(
            name='Fall 2026', session=session1, start_date=base - timedelta(days=5), end_date=base + timedelta(days=150),
            registration_open=timezone.now() - timedelta(days=5), registration_close=timezone.now() + timedelta(days=30),
        )
        # A second, differently-named row for the SAME real term - exactly
        # the kind of near-duplicate a second seed/import run produces.
        session2 = AcademicSession.objects.create(year='2026-2027 (dup)', start_date=base - timedelta(days=3), end_date=base + timedelta(days=302))
        self.sem_b = Semester.objects.create(
            name='Fall 2026 - 2026-2027', session=session2, start_date=base - timedelta(days=3), end_date=base + timedelta(days=152),
            registration_open=timezone.now() - timedelta(days=5), registration_close=timezone.now() + timedelta(days=30),
        )

        user = User.objects.create_user('dupreg_student', password='pw')
        self.student = Student.objects.create(user=user, full_name='Dup Reg Test', admission_no='DRT-001', program=program, status='active')
        CourseRegistration.objects.create(student=self.student, section=self.section, semester=self.sem_a, status='registered')

    def test_registering_under_the_overlapping_duplicate_semester_is_blocked(self):
        from core.services.academic import AcademicEligibilityService
        with self.assertRaises(ValueError) as ctx:
            AcademicEligibilityService.register_course(self.student, self.section.pk, self.sem_b)
        self.assertIn('overlapping', str(ctx.exception))

    def test_data_quality_center_flags_the_overlapping_semesters(self):
        from oversight.services import OversightService
        cats = {c.key: c for c in OversightService.data_quality()}
        self.assertIn('overlap_semesters', cats)
        self.assertEqual(cats['overlap_semesters'].count, 1)
