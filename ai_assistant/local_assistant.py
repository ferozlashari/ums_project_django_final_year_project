"""Zero-cost, privacy-friendly UMS assistant.

This module deliberately uses only Django ORM queries and Python's standard
library. It is the default assistant, so the university portal remains useful
without an API key, external model, network call, or paid service.
"""
from __future__ import annotations

from decimal import Decimal
import re


def _student(user):
    try:
        return user.student_profile
    except Exception:
        return None


def _money(value):
    try:
        return f"{Decimal(value):,.2f}"
    except Exception:
        return str(value)


def answer(user, question: str) -> str:
    q = (question or "").strip().lower()
    if not q:
        return "Please type a question about your university account or campus services."

    role = "admin" if user.is_staff or user.is_superuser else getattr(getattr(user, "profile", None), "role", "student")

    # Student attendance
    if any(k in q for k in ("attendance", "present", "absent")):
        if role != "student":
            return "Attendance details are available from the Attendance module for authorized staff and faculty."
        student = _student(user)
        if not student:
            return "No student record is linked to your account."
        from attendance.models import AttendanceRecord
        records = AttendanceRecord.objects.filter(student=student)
        total = records.count()
        present = records.filter(present=True).count()
        pct = round((present / total) * 100, 1) if total else 0
        return f"Your attendance is {pct}% ({present} present out of {total} recorded classes)."

    # Student fees
    if any(k in q for k in ("fee", "fees", "challan", "payment", "dues", "balance")):
        if role != "student":
            return "Use the Finance module to review authorized fee and payment records."
        student = _student(user)
        if not student:
            return "No student record is linked to your account."
        from finance.models import Invoice
        invoices = Invoice.objects.filter(student=student).order_by("due_date", "id")
        unpaid = invoices.filter(paid=False)
        balance = sum((i.amount for i in unpaid), Decimal("0"))
        if not unpaid:
            return "You have no outstanding fee challans."
        lines = [f"{i.challan_no}: {_money(i.amount)} due {i.due_date}" for i in unpaid[:8]]
        return f"Outstanding balance: {_money(balance)}.\n" + "\n".join(f"• {line}" for line in lines)

    # Grades / GPA
    if any(k in q for k in ("grade", "result", "gpa", "cgpa", "marks")):
        if role != "student":
            return "Authorized faculty and staff can review results through the Exams module."
        student = _student(user)
        if not student:
            return "No student record is linked to your account."
        from exams.models import GradeEntry
        grades = GradeEntry.objects.filter(student=student).select_related("exam__course")
        if not grades.exists():
            return "No grades have been recorded for your account yet."
        credits = 0
        points = Decimal("0")
        for grade in grades:
            c = getattr(grade.exam.course, "credits", 0) or 0
            credits += c
            points += Decimal(str(grade.grade_point or 0)) * c
        cgpa = round(points / credits, 2) if credits else None
        recent = [f"{g.exam.course.code}: {g.grade or 'Pending'}" for g in grades[:8]]
        return f"Current CGPA: {cgpa if cgpa is not None else 'not available'}.\n" + "\n".join(f"• {x}" for x in recent)

    # Library
    if any(k in q for k in ("library", "book", "borrow", "loan")):
        if role == "student":
            student = _student(user)
            if not student:
                return "No student record is linked to your account."
            from library.models import BookLoan
            loans = BookLoan.objects.filter(student=student, status="borrowed").select_related("book")
            if not loans.exists():
                return "You currently have no borrowed library books."
            return "\n".join(f"• {loan.book.title} — due {loan.due_date}" for loan in loans[:10])
        from library.models import Book
        count = Book.objects.count()
        return f"The library currently contains {count} cataloged book records. Open Library search is also available from the Library module."

    # Courses / registration
    if any(k in q for k in ("course", "courses", "register", "registration", "subject", "class")):
        if role == "student":
            student = _student(user)
            if not student:
                return "No student record is linked to your account."
            from academics.models import CourseRegistration
            regs = CourseRegistration.objects.filter(student=student, status="registered").select_related("section__course")
            if not regs.exists():
                return "You are not currently registered in any course sections."
            return "Your registered courses:\n" + "\n".join(f"• {r.section.course.code} — {r.section.course.name}" for r in regs[:12])
        from academics.models import Course
        return f"There are {Course.objects.count()} courses in the academic catalog."

    # Notices
    if any(k in q for k in ("notice", "announcement", "news")):
        from core.models import Notice
        notices = Notice.objects.order_by("-published_at")[:6]
        if not notices:
            return "There are no recent notices."
        return "Recent notices:\n" + "\n".join(f"• {n.title}" for n in notices)

    # Jobs / careers
    if any(k in q for k in ("job", "internship", "career", "placement")):
        from careers.models import JobPosting
        jobs = JobPosting.objects.filter(is_active=True).order_by("application_deadline")[:8]
        if not jobs:
            return "There are no active job or internship postings right now."
        return "Active opportunities:\n" + "\n".join(f"• {j.title}" for j in jobs)

    # Staff risk overview
    if any(k in q for k in ("risk", "at risk", "early warning")):
        if role not in ("admin", "faculty", "staff"):
            return "At-risk student information is restricted to authorized academic staff."
        from risk_analytics.models import RiskFlag
        flags = RiskFlag.objects.filter(is_resolved=False).select_related("student")[:10]
        if not flags:
            return "No unresolved at-risk student flags are currently recorded."
        return "Current unresolved risk flags:\n" + "\n".join(
            f"• {f.student.full_name} — {f.get_level_display()}" for f in flags
        )

    # Admin: exception / data-quality / workflow overview
    if any(k in q for k in ("exception", "needs attention", "data quality", "pending approval", "pending workflow")):
        if role != "admin":
            return "The Exception Center and Data Quality Center are restricted to administrators."
        from oversight.services import OversightService
        from workflow.models import WorkflowRequest
        counts = OversightService.counts()
        pending_wf = WorkflowRequest.objects.filter(status="pending").count()
        return (
            f"Open exceptions: {counts['exceptions']}\n"
            f"Data quality issues: {counts['data_quality']}\n"
            f"Pending workflow requests: {pending_wf}\n"
            "See the Exception Center, Data Quality Center, and Workflow / Approval Center in the admin menu for details."
        )

    if any(k in q for k in ("help", "what can you do", "menu")):
        return (
            "I can help with UMS information such as attendance, fees/challans, "
            "grades/GPA, courses, library loans, notices, careers and authorized "
            "academic risk information. Try: 'show my fees' or 'what is my attendance?'"
        )

    # Small command-style matching for common phrasing.
    if re.search(r"\bhello\b|\bhi\b|\bhey\b", q):
        return "Hello! I can help you navigate the University Management System. Ask me about attendance, fees, results, courses, library, notices, or careers."

    return (
        "I couldn't match that to a UMS topic I can look up (attendance, fees, "
        "challans, results, GPA, courses, library loans, notices, careers, and "
        "more). This offline assistant only answers questions about your UMS "
        "account - for general questions, ask an administrator to configure "
        "an AI provider (Groq/Hugging Face/Gemini) in Site Settings, which "
        "unlocks general conversation too."
    )
