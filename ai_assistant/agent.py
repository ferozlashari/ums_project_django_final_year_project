"""
UMS AI Assistant - built with LangGraph, with a pluggable LLM provider.

The agent is a small ReAct-style graph (LLM node <-> tools node) that can
answer natural-language questions about the university data the *current*
signed-in user is allowed to see (students see only their own records,
staff/admins see aggregate data). It never receives raw model instances -
only small dict/text results returned by the tool functions - which keeps
the prompt free of anything the user shouldn't see and gives us a single
place to enforce access rules.

Two optional external LLM providers are supported, while the built-in local assistant is the default. Providers are switchable from Site Settings (admin ->
Settings -> AI Assistant Provider) with no code change or redeploy:
  - groq         Free, fast (default) - console.groq.com
  - huggingface  Free tier via the Hugging Face Inference API - hf.co/settings/tokens

Only the selected provider's package needs to be installed and its API key
set; the others are optional and imported lazily so a missing package for
an unused provider never breaks the app. If the selected provider isn't
configured, `ask_assistant()` returns a friendly explanatory message
instead of raising, so the rest of the site keeps working.
"""
from __future__ import annotations

import os
from typing import Annotated, TypedDict

from django.conf import settings

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency not installed
    LANGGRAPH_AVAILABLE = False


# Provider display info, keyed the same as SiteSettings.llm_provider choices.
PROVIDER_INFO = {
    'local': {'label': 'Built-in Local Assistant', 'key_env': '', 'free': True},
    'groq': {'label': 'Groq', 'key_env': 'GROQ_API_KEY', 'free': True},
    'huggingface': {'label': 'Hugging Face', 'key_env': 'HUGGINGFACE_API_TOKEN', 'free': True},
    'gemini': {'label': 'Google Gemini', 'key_env': 'GEMINI_API_KEY', 'free': True},
}


def get_active_provider():
    """Which LLM provider is configured, per Site Settings (falls back to
    'local' if the settings row doesn't exist yet, e.g. before first migrate)."""
    try:
        from core.models import SiteSettings
        return SiteSettings.load().llm_provider or 'local'
    except Exception:
        return os.environ.get('LLM_PROVIDER', 'local')


def _get_llm(tools):
    """Instantiate and tool-bind the chat model for whichever provider is
    currently selected. Raises a plain RuntimeError with a clear message on
    missing package/key - the caller (ask_assistant) turns that into a
    friendly reply instead of a stack trace."""
    provider = get_active_provider()
    if provider == 'local':
        raise RuntimeError('The built-in local assistant is active.')
    info = PROVIDER_INFO.get(provider, PROVIDER_INFO['local'])
    api_key = os.environ.get(info['key_env']) or getattr(settings, info['key_env'], None)
    if not api_key:
        raise RuntimeError(
            f"The AI assistant is set to {info['label']}, but {info['key_env']} isn't configured. "
            f"Ask an administrator to set it in .env''."
        )

    if provider == 'groq':
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise RuntimeError("The `langchain-groq` package isn't installed. Run `pip install -r requirements.txt`.")
        model_name = os.environ.get('GROQ_MODEL', getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-120b'))
        llm = ChatGroq(model=model_name, api_key=api_key, temperature=0.2)

    elif provider == 'huggingface':
        try:
            from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        except ImportError:
            raise RuntimeError("The `langchain-huggingface` package isn't installed. Run `pip install -r requirements.txt`.")
        model_name = os.environ.get('HUGGINGFACE_MODEL', getattr(settings, 'HUGGINGFACE_MODEL', 'meta-llama/Llama-3.1-8B-Instruct'))
        endpoint = HuggingFaceEndpoint(repo_id=model_name, huggingfacehub_api_token=api_key, temperature=0.2, max_new_tokens=800)
        llm = ChatHuggingFace(llm=endpoint)

    elif provider == 'gemini':
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise RuntimeError("The `langchain-google-genai` package isn't installed. Run `pip install -r requirements-ai.txt`.")
        model_name = os.environ.get('GEMINI_MODEL', getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash'))
        llm = ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key, temperature=0.2)

    else:
        raise RuntimeError(f"Unknown LLM provider '{provider}'.")

    return llm.bind_tools(tools)


SYSTEM_PROMPT = (
    "You are UMS Assistant, a helpful AI built into a University Management "
    "System. You have tools covering every module: students, courses, "
    "attendance, exams/results, fee challans and real payment options "
    "(bank/JazzCash/EasyPaisa), the library catalog (plus a worldwide book "
    "search via Open Library), hostel applications, complaints, "
    "scholarships, online video classes, the alumni network/mentorship "
    "directory, the career services job/internship board, bus/transport "
    "routes, and GPA/CGPA - and, for signed-in parents/guardians only, a "
    "read-only summary of their verified children's attendance, fees and "
    "grades. Staff/faculty/admin "
    "can also ask about students flagged by the early-warning system. "
    "Always use the tools instead of guessing or inventing numbers. Keep "
    "answers short, friendly and use bullet points for lists. If a tool "
    "reports that the user isn't allowed to see something, say so politely "
    "instead of guessing. For signed-in students you also have ACTION tools "
    "that make real changes - registering into a course section, and "
    "generating a fee challan (semester, hostel or transport fee, "
    "whichever the student is eligible for). These run the same "
    "validation the website itself uses, so a call either succeeds or "
    "returns the exact reason it failed. Never call an action tool unless "
    "the student has clearly asked you to do that specific thing (e.g. "
    "'register me for CS301 section A' or 'generate my semester fee "
    "challan') - if they're only asking what their options are, use the "
    "matching read-only tool instead and describe the options, then ask if "
    "they want you to go ahead. After an action tool runs, report exactly "
    "what it returned - success or the specific reason it was blocked. You "
    "can search the worldwide Open Library book "
    "catalog, but you cannot browse the general internet or visit "
    "arbitrary websites. If the person asks something that has nothing to "
    "do with their UMS data or account - general knowledge, a definition, "
    "casual conversation, help with a study topic - just answer directly "
    "from what you already know, the same as any helpful assistant would; "
    "the 'always use tools' rule above is specifically about UMS facts "
    "(their attendance, fees, grades, etc.), not about every question they "
    "might ask you. Don't deflect a general question back to 'ask about "
    "your attendance/fees/courses' when they didn't ask about those. "
    "The person may speak or type to you in English, "
    "Urdu, or Sindhi (or a mix) - always reply in the same language they "
    "used, written in its native script, since your replies may be read "
    "aloud by text-to-speech."
)


def _build_tools_for_user(user):
    """Return a list of @tool-decorated callables scoped to `user`'s role."""
    from core.views import _user_role
    role = _user_role(user)

    @tool
    def get_notices(limit: int = 5) -> str:
        """Return the most recent campus notices/announcements."""
        from core.models import Notice
        items = Notice.objects.order_by('-published_at')[:max(1, min(limit, 20))]
        if not items:
            return "There are no notices yet."
        return "\n".join(f"- {n.title} ({n.published_at.date()})" for n in items)

    @tool
    def get_my_attendance() -> str:
        """Return the signed-in student's own attendance summary. Students only."""
        if role != 'student':
            return "Only students can check personal attendance with this tool."
        from attendance.models import AttendanceRecord
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        qs = AttendanceRecord.objects.filter(student=student)
        total = qs.count()
        present = qs.filter(present=True).count()
        pct = round((present / total) * 100, 1) if total else 0
        return f"Attendance: {present}/{total} classes present ({pct}%)."

    @tool
    def get_my_fee_status() -> str:
        """Return the signed-in student's own invoices/fee balance, including
        due dates - answers questions like 'when is my fee due?'. Students only."""
        if role != 'student':
            return "Only students can check personal fee status with this tool."
        from finance.models import Invoice
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        invoices = Invoice.objects.filter(student=student)
        total = sum(float(i.amount) for i in invoices)
        outstanding = sum(float(i.amount) for i in invoices if not i.paid)
        unpaid = invoices.filter(paid=False).order_by('due_date')
        if not unpaid:
            return f"Total invoiced: {total:.2f}. No outstanding balance - all challans are paid."
        lines = [f"- {i.challan_no} ({i.get_category_display()}): {i.amount} due {i.due_date}" for i in unpaid]
        return (
            f"Total invoiced: {total:.2f}. Outstanding balance: {outstanding:.2f}.\n"
            "Unpaid challans:\n" + "\n".join(lines)
        )

    @tool
    def get_my_grades() -> str:
        """Return the signed-in student's own exam grades. Students only."""
        if role != 'student':
            return "Only students can check personal grades with this tool."
        from exams.models import GradeEntry
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        entries = GradeEntry.objects.filter(student=student).select_related('exam')
        if not entries:
            return "No grades recorded yet."
        return "\n".join(f"- {e.exam.name}: {e.marks} ({e.grade or 'n/a'})" for e in entries)

    @tool
    def get_institution_stats() -> str:
        """Return aggregate school-wide stats (students, staff, courses, unpaid invoices). Staff/admin only."""
        if role not in ('admin', 'faculty', 'staff'):
            return "Only staff and admin accounts can view institution-wide statistics."
        from registration.models import Student
        from academics.models import Course
        from hr.models import Staff
        from finance.models import Invoice
        return (
            f"Students: {Student.objects.count()}\n"
            f"Staff: {Staff.objects.count()}\n"
            f"Courses: {Course.objects.count()}\n"
            f"Unpaid invoices: {Invoice.objects.filter(paid=False).count()}"
        )

    @tool
    def get_attendance_overview() -> str:
        """Return school-wide attendance percentage. Staff/admin only."""
        if role not in ('admin', 'faculty', 'staff'):
            return "Only staff and admin accounts can view institution-wide attendance."
        from attendance.models import AttendanceRecord
        total = AttendanceRecord.objects.count()
        present = AttendanceRecord.objects.filter(present=True).count()
        pct = round((present / total) * 100, 1) if total else 0
        return f"School-wide attendance: {present}/{total} ({pct}%)."

    @tool
    def get_my_semester_result(semester_name: str = "") -> str:
        """Return the signed-in student's exam results, optionally filtered by
        semester name (e.g. 'Fall 2025'). Shows pass/fail and regular/improvement status. Students only."""
        if role != 'student':
            return "Only students can check personal results with this tool."
        from exams.models import GradeEntry
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        entries = GradeEntry.objects.filter(student=student).select_related('exam', 'exam__semester')
        if semester_name:
            entries = entries.filter(exam__semester__name__icontains=semester_name)
        if not entries:
            return "No results found."
        lines = [f"- {e.exam.course.code}: {e.marks}/{e.exam.max_marks} ({e.percentage}%) - {e.result_label}" for e in entries]
        return "\n".join(lines)

    @tool
    def get_my_fee_challans() -> str:
        """List the signed-in student's fee challans with challan numbers and payment status. Students only."""
        if role != 'student':
            return "Only students can check personal fee challans with this tool."
        from finance.models import Invoice
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        invoices = Invoice.objects.filter(student=student)
        if not invoices:
            return "No fee challans found."
        return "\n".join(
            f"- {i.challan_no}: {i.get_category_display()} - Rs.{i.amount} - {'PAID' if i.paid else ('OVERDUE' if i.is_overdue else 'UNPAID')}"
            for i in invoices
        )

    @tool
    def search_library_catalog(query: str) -> str:
        """Search the campus library's own catalog by title, author, or category."""
        from library.models import Book
        books = Book.objects.filter(title__icontains=query) | Book.objects.filter(author__icontains=query)
        books = books[:8]
        if not books:
            return f"No books found in the campus library matching '{query}'. Try search_worldwide_books for a wider search."
        return "\n".join(f"- {b.title} by {b.author or 'Unknown'} ({b.available_copies}/{b.total_copies} available)" for b in books)

    @tool
    def search_worldwide_books(query: str) -> str:
        """Search millions of books from around the world (via the free Open
        Library catalog) - useful when a book isn't in the campus library, or
        for general reading/research recommendations. Requires the server to
        have internet access."""
        from library.views import search_open_library
        results, error = search_open_library(query, limit=6)
        if error:
            return f"Worldwide search unavailable right now: {error}"
        if not results:
            return f"No worldwide results found for '{query}'."
        return "\n".join(
            f"- {r['title']} by {r['author'] or 'Unknown'} ({r['year'] or 'n/a'})"
            + (f" - read online: {r['read_online_url']}" if r['read_online_url'] else "")
            for r in results
        )

    @tool
    def get_my_library_loans() -> str:
        """List the signed-in student's borrowed library books and due dates. Students only."""
        if role != 'student':
            return "Only students can check personal library loans with this tool."
        from library.models import BookLoan
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        loans = BookLoan.objects.filter(student=student, status='borrowed').select_related('book')
        if not loans:
            return "No books currently borrowed."
        return "\n".join(f"- {l.book.title} (due {l.due_date}{', OVERDUE' if l.is_overdue else ''})" for l in loans)

    @tool
    def get_my_hostel_status() -> str:
        """Return the signed-in student's hostel application status. Students only."""
        if role != 'student':
            return "Only students can check personal hostel status with this tool."
        from hostel.models import HostelApplication
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        app = HostelApplication.objects.filter(student=student).order_by('-applied_at').first()
        if not app:
            return "No hostel application on file. The student can apply from the Hostel page."
        return f"Status: {app.get_status_display()}. Room: {app.assigned_room or 'not yet assigned'}."

    @tool
    def get_my_complaints() -> str:
        """List the signed-in user's own submitted complaints and their status."""
        from complaints.models import Complaint
        items = Complaint.objects.filter(user=user)[:10]
        if not items:
            return "No complaints submitted."
        return "\n".join(f"- {c.subject} [{c.get_category_display()}]: {c.get_status_display()}" for c in items)

    @tool
    def get_available_scholarships() -> str:
        """List currently active scholarship programs available to apply for."""
        from scholarships.models import Scholarship
        items = Scholarship.objects.filter(active=True)[:10]
        if not items:
            return "No active scholarship programs right now."
        return "\n".join(f"- {s.name}: Rs.{s.amount} (deadline: {s.application_deadline or 'rolling'})" for s in items)

    @tool
    def get_my_scholarship_applications() -> str:
        """List the signed-in student's scholarship applications and their status. Students only."""
        if role != 'student':
            return "Only students can check personal scholarship applications with this tool."
        from scholarships.models import ScholarshipApplication
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        apps = ScholarshipApplication.objects.filter(student=student).select_related('scholarship')
        if not apps:
            return "No scholarship applications submitted yet."
        return "\n".join(f"- {a.scholarship.name}: {a.get_status_display()}" for a in apps)

    @tool
    def get_pending_hostel_and_payments_overview() -> str:
        """Return counts of pending hostel applications and unconfirmed payments needing staff review. Staff/admin only."""
        if role not in ('admin', 'faculty', 'staff'):
            return "Only staff and admin accounts can view this overview."
        from hostel.models import HostelApplication
        from finance.models import Payment
        from complaints.models import Complaint
        return (
            f"Pending hostel applications: {HostelApplication.objects.filter(status='pending').count()}\n"
            f"Payments awaiting confirmation: {Payment.objects.filter(status='pending').count()}\n"
            f"Open/in-progress complaints: {Complaint.objects.filter(status__in=['open', 'in_progress']).count()}"
        )

    @tool
    def get_course_catalog(query: str = "") -> str:
        """List available courses and programs, optionally filtered by a
        keyword matching course name/code or program name."""
        from academics.models import Course
        courses = Course.objects.select_related('program').all()
        if query:
            courses = courses.filter(name__icontains=query) | courses.filter(code__icontains=query) | courses.filter(program__name__icontains=query)
        courses = courses[:15]
        if not courses:
            return f"No courses found{f' matching {query!r}' if query else ''}."
        return "\n".join(f"- {c.code}: {c.name} ({c.credits} credits) - {c.program.name if c.program else 'Unassigned program'}" for c in courses)

    @tool
    def get_my_upcoming_classes() -> str:
        """List the signed-in user's upcoming/live online classes (Jitsi video classes)."""
        from onlineclass.models import OnlineClass
        from django.utils import timezone
        from registration.models import Student
        classes = OnlineClass.objects.filter(status__in=['scheduled', 'live']).select_related('section__course', 'host').order_by('scheduled_at')
        if role == 'student':
            try:
                classes = classes.filter(section__course__program=Student.objects.get(user=user).program)
            except Exception:
                return "No student record is linked to this account."
        elif role in ('faculty', 'staff'):
            try:
                classes = classes.filter(host=user.staff_profile)
            except Exception:
                pass
        classes = classes[:8]
        if not classes:
            return "No upcoming online classes scheduled."
        return "\n".join(f"- {c.title} ({c.section.course.code}) - {c.scheduled_at.strftime('%b %d, %H:%M')} - {c.get_status_display()}" for c in classes)

    @tool
    def get_payment_options() -> str:
        """Return this institution's real bank account, JazzCash and EasyPaisa
        details for paying a fee challan, exactly as configured by the admin
        in Site Settings. Use this whenever someone asks how/where to pay."""
        from finance.views import get_payment_details
        d = get_payment_details()
        return (
            f"Bank: {d['bank_name']} - Account Title: {d['account_title']}\n"
            f"Account No: {d['account_no']} - IBAN: {d['iban']}\n"
            f"JazzCash: {d['jazzcash_number']}\n"
            f"EasyPaisa: {d['easypaisa_number']}\n"
            "After paying with any of these, go to the challan's Pay Now page and submit the "
            "transaction reference so the accounts office can confirm it."
        )

    @tool
    def search_alumni_directory(query: str = "") -> str:
        """Search the public alumni directory by employer, industry, or name -
        useful for career guidance, networking, or mentorship questions.
        Only public profiles are returned."""
        from alumni.models import AlumniProfile
        profiles = AlumniProfile.objects.filter(is_public=True).select_related('student')
        if query:
            profiles = (
                profiles.filter(current_employer__icontains=query)
                | profiles.filter(industry__icontains=query)
                | profiles.filter(student__full_name__icontains=query)
            )
        profiles = profiles.distinct()[:8]
        if not profiles:
            return f"No public alumni profiles found{f' matching {query!r}' if query else ''}."
        return "\n".join(
            f"- {p.student.full_name} ({p.graduation_year}): {p.job_title or 'n/a'} at {p.current_employer or 'n/a'}"
            + (" - open to mentoring" if p.willing_to_mentor else "")
            for p in profiles
        )

    @tool
    def get_my_children_summary() -> str:
        """Return attendance %, unpaid fee total, and latest grade for every
        student the signed-in guardian has a *verified* link to. Guardians only."""
        if role != 'guardian':
            return "Only guardian/parent accounts can use this tool."
        from parents.models import GuardianLink
        from attendance.models import AttendanceRecord
        from finance.models import Invoice
        from exams.models import GradeEntry
        links = GuardianLink.objects.filter(guardian=user, is_verified=True).select_related('student')
        if not links:
            return "No verified student links yet. Ask an admin to verify your guardian link request."
        lines = []
        for link in links:
            s = link.student
            total = AttendanceRecord.objects.filter(student=s).count()
            present = AttendanceRecord.objects.filter(student=s, present=True).count()
            pct = round((present / total) * 100, 1) if total else None
            unpaid = sum((float(i.amount) for i in Invoice.objects.filter(student=s, paid=False)), start=0.0)
            latest = GradeEntry.objects.filter(student=s).order_by('-id').first()
            grade_txt = f"{latest.exam}: {latest.marks} ({latest.percentage}%)" if latest else "no grades yet"
            lines.append(
                f"- {s.full_name}: attendance {pct if pct is not None else 'n/a'}%, "
                f"unpaid fees Rs.{unpaid:.2f}, latest grade - {grade_txt}"
            )
        return "\n".join(lines)

    @tool
    def get_job_postings(query: str = "") -> str:
        """List open job/internship postings, optionally filtered by title,
        employer, or major keyword. Available to everyone (students browsing
        the career board, staff checking what's posted)."""
        from careers.models import JobPosting
        postings = JobPosting.objects.filter(is_active=True).select_related('employer')
        if query:
            postings = (
                postings.filter(title__icontains=query)
                | postings.filter(employer__name__icontains=query)
                | postings.filter(relevant_majors__icontains=query)
            )
        postings = postings.distinct()[:8]
        if not postings:
            return f"No open postings found{f' matching {query!r}' if query else ''}."
        return "\n".join(
            f"- {p.title} @ {p.employer.name} ({p.get_posting_type_display()})"
            + (f", deadline {p.application_deadline}" if p.application_deadline else "")
            for p in postings
        )

    @tool
    def get_my_job_applications() -> str:
        """List the signed-in student's own job/internship applications and their status."""
        from careers.models import JobApplication
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        apps = JobApplication.objects.filter(student=student).select_related('posting', 'posting__employer')
        if not apps:
            return "No job applications submitted yet."
        return "\n".join(f"- {a.posting.title} @ {a.posting.employer.name}: {a.get_status_display()}" for a in apps)

    @tool
    def get_at_risk_students_summary() -> str:
        """Staff/faculty/admin only: summarize students currently flagged by
        the early-warning system (low attendance and/or low grades), scoped
        to only the students the signed-in teacher actually teaches."""
        if role not in ('faculty', 'staff', 'admin'):
            return "Only staff, faculty, or admin accounts can use this tool."
        from risk_analytics.models import RiskFlag
        from registration.models import Student
        from core.permissions import section_scope_students
        flags = RiskFlag.objects.filter(is_resolved=False).select_related('student')
        if role in ('faculty', 'staff'):
            my_students = section_scope_students(user, Student.objects.all())
            flags = flags.filter(student__in=my_students)
        flags = flags[:10]
        if not flags:
            return "No students are currently flagged as at-risk."
        return "\n".join(
            f"- {f.student.full_name}: {f.get_level_display()} risk - {f.reasons.splitlines()[0] if f.reasons else ''}"
            for f in flags
        )

    @tool
    def get_my_transport() -> str:
        """Return the signed-in student's bus route, pickup stop, and pickup
        time - answers 'what is my bus route?'. Students only."""
        if role != 'student':
            return "Only students can check personal transport info with this tool."
        from transport.models import StudentTransportAssignment
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        assignment = StudentTransportAssignment.objects.filter(student=student, is_active=True).select_related('route', 'stop', 'route__vehicle').first()
        if not assignment:
            return "No transport route is assigned yet - contact the transport office to sign up."
        parts = [f"You are assigned to {assignment.route.name}."]
        if assignment.stop:
            parts.append(f"Pickup: {assignment.stop.name} at {assignment.stop.pickup_time.strftime('%I:%M %p')}.")
        if assignment.route.vehicle:
            parts.append(f"Vehicle: {assignment.route.vehicle.registration_no}.")
        return " ".join(parts)

    # --- Agentic action tools: these don't just read data, they perform the
    # same validated action a student would take by clicking a button on the
    # site. Each one reuses the exact same service/eligibility code the web
    # views call, so the assistant can never bypass a check a human would
    # have to satisfy. All are student-only and act only on the signed-in
    # user's own record - never on another student's.

    @tool
    def register_for_course_section(section_id: int) -> str:
        """Register the signed-in student into a course section for the
        current semester. Runs the exact same eligibility checks as the
        Course Registration page (program match, prerequisites, seat
        availability, credit-hour limit, registration window). Students
        only - use get_course_catalog or search first to find the
        section_id."""
        if role != 'student':
            return "Only students can register for a course through this tool."
        from registration.models import Student
        from core.services.academic import AcademicEligibilityService
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        try:
            registration = AcademicEligibilityService.register_course(student, section_id)
        except Exception as exc:
            return f"Could not register: {exc}"
        return f"Registered: {registration.section.course.code} - {registration.section.code} for {registration.semester}."

    @tool
    def generate_fee_challan(kind: str) -> str:
        """Generate the signed-in student's own challan for the given fee
        type. kind must be one of: 'semester', 'hostel' or 'transport'.
        Each type has its own eligibility rule (e.g. hostel needs an
        approved room allocation, transport needs an active route
        assignment) and
        this tool enforces exactly the same rule the 'Fee & Challan
        Management' page buttons do - it will explain why if the student
        isn't eligible for that type. Students only."""
        if role != 'student':
            return "Only students can generate their own fee challans."
        from registration.models import Student
        from finance.services import FeeChallanService
        method = {
            'semester': FeeChallanService.generate_semester_fee,
            'hostel': FeeChallanService.generate_hostel_fee,
            'transport': FeeChallanService.generate_transport_fee,
            }.get(kind)
        if method is None:
            return "Unknown challan type. Valid types: semester, hostel, transport."
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        result = method(student)
        return result.message

    @tool
    def check_my_exam_slip_eligibility() -> str:
        """Check whether the signed-in student is currently eligible for
        the exam admit slip (attendance >= the configured minimum AND no
        unpaid semester fee) - same gate as the printable Exam Slip page,
        so the assistant's answer always matches what the page would show.
        Students only."""
        if role != 'student':
            return "Only students can check their own exam slip eligibility."
        from registration.models import Student
        from attendance.models import AttendanceRecord
        from finance.models import Invoice
        from core.models import SiteSettings
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        records = AttendanceRecord.objects.filter(student=student)
        total = records.count()
        present = records.filter(present=True).count()
        pct = round((present / total) * 100, 1) if total else 0
        min_pct = float(SiteSettings.load().minimum_attendance_percent)
        unpaid = Invoice.objects.filter(student=student, category='semester', paid=False).first()
        if pct >= min_pct and not unpaid:
            return f"Eligible - attendance is {pct}% (minimum {min_pct}%) and the semester fee is paid."
        reasons = []
        if pct < min_pct:
            reasons.append(f"attendance is {pct}%, below the {min_pct}% minimum")
        if unpaid:
            reasons.append(f"unpaid semester challan {unpaid.challan_no}")
        return "Not eligible yet: " + "; ".join(reasons) + "."

    @tool
    def get_my_gpa() -> str:
        """Return the signed-in student's GPA per semester and overall CGPA. Students only."""
        if role != 'student':
            return "Only students can check personal GPA with this tool."
        from exams.models import GradeEntry
        from registration.models import Student
        try:
            student = Student.objects.get(user=user)
        except Student.DoesNotExist:
            return "No student record is linked to this account."
        grades = GradeEntry.objects.filter(student=student).select_related('exam__course', 'exam__semester')
        if not grades:
            return "No grades recorded yet, so GPA can't be calculated."
        total_points, total_credits = 0.0, 0
        for g in grades:
            credits = g.exam.course.credits or 0
            total_points += g.grade_point * credits
            total_credits += credits
        cgpa = round(total_points / total_credits, 2) if total_credits else None
        return f"Your current CGPA is {cgpa} (out of 4.00), based on {total_credits} credit hours completed."

    @tool
    def get_exceptions_summary() -> str:
        """Admin only: summarize open items in the Exception Center and
        Data Quality Center - registration/prerequisite problems, capacity
        and timetable conflicts, missing marks, low attendance, finance
        exceptions, duplicate records, and incomplete profiles. Use this
        for questions like 'what needs attention today' or 'summarize
        today's university operations'."""
        if role != 'admin':
            return "Only admin accounts can view the Exception Center / Data Quality Center summary."
        from oversight.services import OversightService
        lines = ["Exception Center:"]
        for cat in OversightService.exceptions():
            if cat.count:
                lines.append(f"- {cat.label}: {cat.count}")
        if len(lines) == 1:
            lines.append("- Nothing open.")
        lines.append("\nData Quality Center:")
        dq_start = len(lines)
        for cat in OversightService.data_quality():
            if cat.count:
                lines.append(f"- {cat.label}: {cat.count}")
        if len(lines) == dq_start:
            lines.append("- No issues detected.")
        return "\n".join(lines)

    @tool
    def get_pending_workflow_requests() -> str:
        """Admin only: list pending Workflow/Approval Center requests
        (marks corrections, fee adjustments, and other exceptions) waiting
        for a decision."""
        if role != 'admin':
            return "Only admin accounts can view pending workflow requests."
        from workflow.models import WorkflowRequest
        pending = WorkflowRequest.objects.filter(status='pending').select_related('requested_by')[:15]
        if not pending:
            return "No pending workflow requests."
        return "\n".join(
            f"- #{r.pk} {r.get_request_type_display()} by {r.requested_by}: {r.subject} ({r.old_value} -> {r.new_value})"
            for r in pending
        )

    return [
        get_notices, get_my_attendance, get_my_fee_status, get_my_grades,
        get_institution_stats, get_attendance_overview,
        get_my_semester_result, get_my_fee_challans,
        search_library_catalog, search_worldwide_books, get_my_library_loans,
        get_my_hostel_status, get_my_complaints,
        get_available_scholarships, get_my_scholarship_applications,
        get_pending_hostel_and_payments_overview, get_my_upcoming_classes,
        get_course_catalog, get_payment_options, search_alumni_directory,
        get_my_children_summary, get_job_postings, get_my_job_applications,
        get_at_risk_students_summary, get_my_transport, get_my_gpa,
        register_for_course_section, generate_fee_challan,
        check_my_exam_slip_eligibility, get_exceptions_summary,
        get_pending_workflow_requests,
    ]


if LANGGRAPH_AVAILABLE:

    class AgentState(TypedDict):
        messages: Annotated[list, add_messages]

    def _make_graph(user):
        tools = _build_tools_for_user(user)
        llm = _get_llm(tools)

        def call_model(state: AgentState):
            messages = state['messages']
            response = llm.invoke(messages)
            return {'messages': [response]}

        def should_continue(state: AgentState):
            last = state['messages'][-1]
            if isinstance(last, AIMessage) and getattr(last, 'tool_calls', None):
                return 'tools'
            return END

        graph = StateGraph(AgentState)
        graph.add_node('agent', call_model)
        graph.add_node('tools', ToolNode(tools))
        graph.set_entry_point('agent')
        graph.add_conditional_edges('agent', should_continue, {'tools': 'tools', END: END})
        graph.add_edge('tools', 'agent')
        return graph.compile()


def ask_assistant(user, question: str, history: list[dict] | None = None) -> dict:
    """Run the LangGraph agent for `question` and return {'answer', 'error'}.

    `history` is a list of {'role': 'user'|'assistant', 'content': str} used
    to give the agent short-term memory of the current conversation.
    """
    # Local assistant is the default and requires no API, network, or model.
    provider = get_active_provider()
    if provider == 'local' or not LANGGRAPH_AVAILABLE:
        from .local_assistant import answer as local_answer
        return {'answer': local_answer(user, question), 'error': None}

    try:
        graph = _make_graph(user)
    except RuntimeError:
        from .local_assistant import answer as local_answer
        return {'answer': local_answer(user, question), 'error': None}

    try:
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for turn in (history or [])[-10:]:
            if turn.get('role') == 'user':
                messages.append(HumanMessage(content=turn['content']))
            else:
                messages.append(AIMessage(content=turn['content']))
        messages.append(HumanMessage(content=question))

        result = graph.invoke({'messages': messages})
        final = result['messages'][-1]
        return {'answer': getattr(final, 'content', str(final)), 'error': None}
    except Exception as exc:  # pragma: no cover - network/API errors at runtime
        from .local_assistant import answer as local_answer
        return {'answer': local_answer(user, question), 'error': 'local_fallback'}
