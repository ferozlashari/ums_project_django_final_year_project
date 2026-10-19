"""
Exception Center + Data Quality Center detection logic.

Every finding here is computed live from the real database - nothing is
hard-coded or simulated. Each check returns a list of `Finding` objects.
Findings are *read-only diagnostics*: this module never mutates data. An
admin who wants to fix something clicks through to the normal admin page
for that record (Django admin, or the app's own edit view) and makes the
change there, so the usual audit trail still applies.

Two entry points:
    OversightService.exceptions()    -> "Exception Center" findings
    OversightService.data_quality()  -> "Data Quality Center" findings

Both are grouped into categories so the templates can render them as
collapsible sections, and each category carries a `count` used for the
dashboard's "Needs Attention" widget (see core.views.admin_dashboard).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.db.models import Count, Q

LOW_ATTENDANCE_THRESHOLD = 75  # percent - matches the figure used elsewhere in the UI


@dataclass
class Finding:
    title: str
    detail: str
    severity: str = "medium"   # low | medium | high
    link: str | None = None
    link_label: str = "View"


@dataclass
class Category:
    key: str
    label: str
    icon: str
    findings: list = field(default_factory=list)

    @property
    def count(self):
        return len(self.findings)


def _admin_link(obj):
    """Best-effort link to this object's Django admin change page. Never
    raises - a broken/missing admin registration just means no link,
    not a crashed page."""
    try:
        return reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
    except NoReverseMatch:
        return None


class OversightService:
    # ------------------------------------------------------------------
    # EXCEPTION CENTER - things that need a human decision right now
    # ------------------------------------------------------------------
    @classmethod
    def exceptions(cls):
        return [
            cls._registration_and_prerequisite_exceptions(),
            cls._capacity_and_teacher_exceptions(),
            cls._timetable_conflicts(),
            cls._missing_marks(),
            cls._low_attendance(),
            cls._fee_exceptions(),
        ]

    @staticmethod
    def _registration_and_prerequisite_exceptions():
        from academics.models import CourseRegistration
        from exams.models import GradeEntry

        cat = Category("registration", "Registration & Prerequisite Exceptions", "📝")
        regs = (
            CourseRegistration.objects.filter(status="registered")
            .select_related("student", "section__course", "semester")
            .prefetch_related("section__course__prerequisites")
        )
        # Preload which courses each student has already passed, once.
        # `status` is a computed property on GradeEntry (not a DB field),
        # so we evaluate it in Python rather than filtering in SQL.
        passed_by_student = {}
        for entry in GradeEntry.objects.select_related("exam"):
            if entry.status == "pass":
                passed_by_student.setdefault(entry.student_id, set()).add(entry.exam.course_id)

        for reg in regs:
            course = reg.section.course
            if course.program_id != (reg.student.active_program_id if reg.student else None):
                cat.findings.append(Finding(
                    title=f"{reg.student.full_name} registered outside their program",
                    detail=f"{course.code} belongs to a different program than {reg.student.full_name}'s ({reg.student.active_program}).",
                    severity="high",
                    link=_admin_link(reg), link_label="View registration",
                ))
            missing = [
                c.code for c in course.prerequisites.all()
                if c.id not in passed_by_student.get(reg.student_id, set())
            ]
            if missing:
                cat.findings.append(Finding(
                    title=f"{reg.student.full_name} - prerequisite not satisfied",
                    detail=f"Registered in {course.code} without passing: {', '.join(missing)}.",
                    severity="high",
                    link=_admin_link(reg), link_label="View registration",
                ))
        return cat

    @staticmethod
    def _capacity_and_teacher_exceptions():
        from academics.models import CourseSection

        cat = Category("capacity", "Capacity & Teacher Assignment Exceptions", "🏫")
        sections = CourseSection.objects.select_related("course", "instructor").annotate(
            reg_count=Count("registrations", filter=Q(registrations__status="registered"))
        )
        for s in sections:
            if s.reg_count > s.capacity:
                cat.findings.append(Finding(
                    title=f"{s} is over capacity",
                    detail=f"{s.reg_count} registered against a capacity of {s.capacity}.",
                    severity="high",
                    link=_admin_link(s), link_label="View section",
                ))
            if s.instructor_id is None and s.reg_count > 0:
                cat.findings.append(Finding(
                    title=f"{s} has no teacher assigned",
                    detail=f"{s.reg_count} student(s) registered but no instructor is set.",
                    severity="high",
                    link=_admin_link(s), link_label="View section",
                ))
        return cat

    @staticmethod
    def _timetable_conflicts():
        from timetable.models import TimetableAssignment

        cat = Category("timetable", "Timetable Conflicts", "🕒")
        assignments = TimetableAssignment.objects.select_related(
            "section__instructor", "room", "timeslot", "section__course"
        )
        by_instructor_slot = {}
        by_room_slot = {}
        for a in assignments:
            slot_key = (a.timeslot.day, a.timeslot.start_time, a.timeslot.end_time)
            if a.section.instructor_id:
                key = (a.section.instructor_id, slot_key)
                by_instructor_slot.setdefault(key, []).append(a)
            room_key = (a.room_id, slot_key)
            by_room_slot.setdefault(room_key, []).append(a)

        seen = set()
        for (instr_id, slot), group in by_instructor_slot.items():
            if len(group) > 1:
                names = ", ".join(f"{g.section}" for g in group)
                fp = ("instr", instr_id, slot)
                if fp not in seen:
                    seen.add(fp)
                    cat.findings.append(Finding(
                        title=f"{group[0].section.instructor} double-booked",
                        detail=f"Teaching {names} at the same time ({slot[0]} {slot[1]}-{slot[2]}).",
                        severity="high",
                        link=_admin_link(group[0]), link_label="View timetable entry",
                    ))
        for (room_id, slot), group in by_room_slot.items():
            if len(group) > 1:
                names = ", ".join(f"{g.section}" for g in group)
                fp = ("room", room_id, slot)
                if fp not in seen:
                    seen.add(fp)
                    cat.findings.append(Finding(
                        title=f"{group[0].room} double-booked",
                        detail=f"{names} are scheduled in the same room at the same time ({slot[0]} {slot[1]}-{slot[2]}).",
                        severity="medium",
                        link=_admin_link(group[0]), link_label="View timetable entry",
                    ))
        return cat

    @staticmethod
    def _missing_marks():
        from exams.models import ExamSession, GradeEntry
        from academics.models import CourseRegistration

        cat = Category("marks", "Missing Marks", "📊")
        today = timezone.localdate()
        overdue_exams = ExamSession.objects.filter(date__lt=today).select_related("course")
        for exam in overdue_exams:
            registered_ids = set(
                CourseRegistration.objects.filter(
                    section__course=exam.course, status="registered"
                ).values_list("student_id", flat=True)
            )
            if not registered_ids:
                continue
            graded_ids = set(
                GradeEntry.objects.filter(exam=exam).values_list("student_id", flat=True)
            )
            missing_count = len(registered_ids - graded_ids)
            if missing_count:
                cat.findings.append(Finding(
                    title=f"{exam} - {missing_count} student(s) not graded",
                    detail=f"Exam date was {exam.date}; {missing_count} of {len(registered_ids)} registered students have no grade entry yet.",
                    severity="medium",
                    link=_admin_link(exam), link_label="View exam",
                ))
        return cat

    @staticmethod
    def _low_attendance():
        from academics.models import CourseSection
        from attendance.models import AttendanceRecord

        cat = Category("attendance", "Low Attendance", "👆")
        sections = CourseSection.objects.select_related("course")
        for section in sections:
            records = AttendanceRecord.objects.filter(section=section).values("student_id").annotate(
                total=Count("id"), present=Count("id", filter=Q(present=True))
            )
            for row in records:
                if row["total"] < 5:
                    continue  # not enough history to judge yet
                pct = round(100 * row["present"] / row["total"])
                if pct < LOW_ATTENDANCE_THRESHOLD:
                    from registration.models import Student
                    try:
                        student = Student.objects.get(pk=row["student_id"])
                    except Student.DoesNotExist:
                        continue
                    cat.findings.append(Finding(
                        title=f"{student.full_name} below attendance threshold in {section}",
                        detail=f"{pct}% present ({row['present']}/{row['total']} sessions) - below the {LOW_ATTENDANCE_THRESHOLD}% threshold.",
                        severity="medium",
                        link=_admin_link(student), link_label="View student",
                    ))
        return cat

    @staticmethod
    def _fee_exceptions():
        from finance.models import Invoice, Payment

        cat = Category("finance", "Finance Exceptions", "💰")
        overdue = Invoice.objects.filter(paid=False, due_date__lt=timezone.localdate()).select_related("student")
        for inv in overdue:
            cat.findings.append(Finding(
                title=f"{inv.challan_no} overdue",
                detail=f"{inv.student.full_name} - {inv.get_category_display()} - PKR {inv.amount} due {inv.due_date}.",
                severity="medium",
                link=_admin_link(inv), link_label="View invoice",
            ))
        stale_pending = Payment.objects.filter(
            status="pending", paid_at__lt=timezone.now() - timedelta(days=3)
        ).select_related("invoice__student")
        for p in stale_pending:
            cat.findings.append(Finding(
                title=f"Payment awaiting verification for {p.invoice.challan_no}",
                detail=f"{p.invoice.student.full_name} submitted PKR {p.amount} via {p.get_method_display() or 'unspecified method'} on {p.paid_at:%Y-%m-%d} - still unconfirmed.",
                severity="low",
                link=_admin_link(p), link_label="View payment",
            ))
        return cat

    # ------------------------------------------------------------------
    # DATA QUALITY CENTER - structural problems in the data itself
    # ------------------------------------------------------------------
    @classmethod
    def data_quality(cls):
        return [
            cls._duplicate_students(),
            cls._duplicate_courses(),
            cls._duplicate_exam_sessions(),
            cls._overlapping_semesters(),
            cls._invalid_prerequisites(),
            cls._orphan_records(),
            cls._incomplete_profiles(),
        ]

    @staticmethod
    def _duplicate_exam_sessions():
        """Two ExamSession rows for the same course+semester (e.g. one
        named "Midterm" and one "Semester exam", each carrying its own
        full component breakdown) mean a student can end up with two
        separate GradeEntry rows for what should be one course result -
        each one independently counted toward CGPA and shown as its own
        retake/improvement opportunity until canonical_grades() dedupes
        them for calculation purposes (see exams/models.py). The extra
        row itself is still real underlying data mess that should be
        cleaned up (merge the two exams, or delete whichever one is
        wrong) rather than just papered over."""
        from exams.models import ExamSession

        cat = Category("dup_exam_sessions", "Duplicate Exam Sessions", "📝")
        dupes = (
            ExamSession.objects.values("course_id", "semester_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1, semester_id__isnull=False)
        )
        for row in dupes:
            sessions = ExamSession.objects.filter(
                course_id=row["course_id"], semester_id=row["semester_id"]
            ).select_related("course", "semester")
            first = sessions.first()
            names = ", ".join(f'"{s.name}"' for s in sessions)
            cat.findings.append(Finding(
                title=f'{row["n"]} exam sessions for {first.course.code} in {first.semester.display_name if first.semester else "the same semester"}',
                detail=(
                    f"{names}. Any student graded in more than one of these has two separate results "
                    "for the same course - merge these exam sessions into one, or remove whichever is "
                    "the mistaken duplicate."
                ),
                severity="high",
                link=_admin_link(first), link_label="View one record",
            ))
        return cat

    @staticmethod
    def _overlapping_semesters():
        """Two Semester rows covering the same real-world term (e.g. two
        differently-named "Fall 2026" records from separate seed/import
        runs) are a real, confusing data problem - they can let a student
        end up registered twice for the same course (once under each
        row), and produce garbled labels where a semester's own name
        already contains a year that then gets duplicated on display."""
        from academics.models import Semester

        cat = Category("overlap_semesters", "Overlapping Semesters", "🗓️")
        semesters = list(Semester.objects.select_related("session").order_by("start_date"))
        seen_pairs = set()
        for i, a in enumerate(semesters):
            for b in semesters[i + 1:]:
                if a.start_date <= b.end_date and b.start_date <= a.end_date:
                    pair = tuple(sorted((a.pk, b.pk)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    cat.findings.append(Finding(
                        title=f'"{a.display_name}" and "{b.display_name}" have overlapping dates',
                        detail=(
                            f"{a} ({a.start_date} to {a.end_date}) overlaps {b} ({b.start_date} to {b.end_date}). "
                            "If these represent the same real term, merge them - a student can otherwise end up "
                            "registered for the same course under both."
                        ),
                        severity="high",
                        link=_admin_link(a), link_label="View one record",
                    ))
        return cat

    @staticmethod
    def _duplicate_students():
        from registration.models import Student

        cat = Category("dup_students", "Duplicate Students", "👥")
        dupes = (
            Student.objects.values("full_name", "program_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1, full_name__gt="")
        )
        for row in dupes:
            matches = Student.objects.filter(full_name=row["full_name"], program_id=row["program_id"])
            first = matches.first()
            cat.findings.append(Finding(
                title=f'{row["n"]} records named "{row["full_name"]}" in the same program',
                detail="Same name and program - check admission numbers to confirm whether this is a duplicate record or two different students.",
                severity="medium",
                link=_admin_link(first) if first else None, link_label="View one record",
            ))
        return cat

    @staticmethod
    def _duplicate_courses():
        from academics.models import Course

        cat = Category("dup_courses", "Duplicate Courses", "📚")
        dupes = (
            Course.objects.values("code", "program_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        for row in dupes:
            matches = Course.objects.filter(code=row["code"], program_id=row["program_id"])
            first = matches.first()
            cat.findings.append(Finding(
                title=f'{row["n"]} courses with code "{row["code"]}" in the same program',
                detail="Course codes should be unique within a program. Merge or rename the duplicates.",
                severity="high",
                link=_admin_link(first) if first else None, link_label="View one record",
            ))
        return cat

    @staticmethod
    def _invalid_prerequisites():
        from academics.models import Course

        cat = Category("prereqs", "Invalid Prerequisites", "🔗")
        for course in Course.objects.prefetch_related("prerequisites"):
            if course in course.prerequisites.all():
                cat.findings.append(Finding(
                    title=f"{course.code} lists itself as its own prerequisite",
                    detail="A course cannot be a prerequisite of itself - remove the self-reference.",
                    severity="high",
                    link=_admin_link(course), link_label="View course",
                ))
        return cat

    @staticmethod
    def _orphan_records():
        from academics.models import CourseRegistration

        cat = Category("orphans", "Orphan Registrations", "🧩")
        orphans = CourseRegistration.objects.filter(
            Q(student__isnull=True) | Q(section__isnull=True)
        )
        for reg in orphans:
            cat.findings.append(Finding(
                title=f"Registration #{reg.pk} is missing its student or section",
                detail="This registration record no longer points to a valid student and/or section.",
                severity="high",
                link=_admin_link(reg), link_label="View registration",
            ))
        return cat

    @staticmethod
    def _incomplete_profiles():
        from registration.models import Student

        cat = Category("profiles", "Incomplete Student Profiles", "📋")
        incomplete = Student.objects.filter(
            Q(phone="") | Q(address="") | Q(gender="") | Q(program__isnull=True)
        ).filter(status="active")
        for s in incomplete:
            missing = [
                label for label, ok in (
                    ("phone", bool(s.phone)),
                    ("address", bool(s.address)),
                    ("gender", bool(s.gender)),
                    ("program", s.program_id is not None),
                ) if not ok
            ]
            cat.findings.append(Finding(
                title=f"{s.full_name} - incomplete profile",
                detail=f"Missing: {', '.join(missing)}.",
                severity="low",
                link=_admin_link(s), link_label="View student",
            ))
        return cat

    # ------------------------------------------------------------------
    @classmethod
    def counts(cls):
        """Cheap summary used by the admin dashboard's Needs Attention
        widget: total exception count + total data-quality count."""
        try:
            exc_total = sum(c.count for c in cls.exceptions())
        except Exception:
            exc_total = 0
        try:
            dq_total = sum(c.count for c in cls.data_quality())
        except Exception:
            dq_total = 0
        return {"exceptions": exc_total, "data_quality": dq_total}
