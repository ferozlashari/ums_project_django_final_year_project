from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from academics.models import Faculty, Department, Program, Course, CourseSection
from core.models import Profile
from exams.models import ExamSession, GradeEntry
from finance.models import Invoice
from hr.models import Staff
from registration.models import Student
from .models import WorkflowRequest


class WorkflowApprovalTests(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Engineering & CS")
        dept = Department.objects.create(name="Computer Science", faculty=faculty)
        self.program = Program.objects.create(name="BSCS", code="BSCS", department=dept)
        self.course = Course.objects.create(code="CS101", name="Programming Fundamentals", credits=3, program=self.program)

        teacher_user = User.objects.create_user("teacher1", password="pw", first_name="Teacher", last_name="One")
        Profile.objects.filter(user=teacher_user).update(role="faculty")
        self.staff = Staff.objects.create(user=teacher_user, employee_id="EMP-001", department=dept)
        self.section = CourseSection.objects.create(course=self.course, code="A", instructor=self.staff, capacity=30)

        student_user = User.objects.create_user("stu1", password="pw")
        self.student = Student.objects.create(
            user=student_user, full_name="Ali Raza", admission_no="BSCS-001",
            program=self.program, status="active",
        )

        self.exam = ExamSession.objects.create(name="Midterm", course=self.course, date="2026-01-10", max_marks=100)
        self.grade = GradeEntry.objects.create(student=self.student, exam=self.exam, marks=Decimal("55"))

        self.invoice = Invoice.objects.create(student=self.student, amount=Decimal("10000"), category="semester")

        admin_user = User.objects.create_user("adm1", password="pw", is_staff=True, is_superuser=True)
        self.admin = admin_user
        from governance.models import EmergencyAccess      # break-glass window while no office holder exists
        from django.utils import timezone as _tz
        import datetime as _dt
        EmergencyAccess.objects.create(user=self.admin, reason='Test: no office holders configured yet', expires_at=_tz.now() + _dt.timedelta(minutes=30))
        self.teacher_user = teacher_user

    def test_teacher_can_submit_marks_correction_request(self):
        self.client.force_login(self.teacher_user)
        resp = self.client.post(reverse("submit-workflow-request"), {
            "request_type": "marks_correction",
            "grade_entry": self.grade.pk,
            "old_value": "55", "new_value": "65",
            "reason": "Marking error - forgot to add lab component.",
        })
        self.assertEqual(resp.status_code, 302)
        wr = WorkflowRequest.objects.get()
        self.assertEqual(wr.status, "pending")
        self.assertEqual(wr.requested_by, self.teacher_user)

    def test_admin_approve_applies_marks_correction(self):
        wr = WorkflowRequest.objects.create(
            request_type="marks_correction", requested_by=self.teacher_user,
            grade_entry=self.grade, old_value="55", new_value="65", reason="fix",
        )
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("workflow-approve", args=[wr.pk]), {"notes": "ok"})
        self.assertEqual(resp.status_code, 302)
        self.grade.refresh_from_db()
        wr.refresh_from_db()
        self.assertEqual(self.grade.marks, Decimal("65"))
        self.assertTrue(self.grade.admin_unlocked)
        self.assertEqual(wr.status, "approved")
        self.assertEqual(wr.decided_by, self.admin)

    def test_admin_approve_applies_fee_adjustment(self):
        wr = WorkflowRequest.objects.create(
            request_type="fee_adjustment", requested_by=self.admin,
            invoice=self.invoice, old_value="10000", new_value="8000", reason="scholarship discount",
        )
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("workflow-approve", args=[wr.pk]), {"notes": "approved"})
        self.assertEqual(resp.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal("8000"))

    def test_admin_reject_does_not_change_grade(self):
        wr = WorkflowRequest.objects.create(
            request_type="marks_correction", requested_by=self.teacher_user,
            grade_entry=self.grade, old_value="55", new_value="99", reason="fix",
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("workflow-reject", args=[wr.pk]), {"notes": "not justified"})
        self.grade.refresh_from_db()
        wr.refresh_from_db()
        self.assertEqual(self.grade.marks, Decimal("55"))
        self.assertEqual(wr.status, "rejected")

    def test_non_admin_cannot_approve(self):
        wr = WorkflowRequest.objects.create(
            request_type="marks_correction", requested_by=self.teacher_user,
            grade_entry=self.grade, old_value="55", new_value="65", reason="fix",
        )
        self.client.force_login(self.teacher_user)
        resp = self.client.post(reverse("workflow-approve", args=[wr.pk]), {"notes": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_invalid_new_value_does_not_crash_or_apply(self):
        wr = WorkflowRequest.objects.create(
            request_type="marks_correction", requested_by=self.teacher_user,
            grade_entry=self.grade, old_value="55", new_value="not-a-number", reason="fix",
        )
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("workflow-approve", args=[wr.pk]), {"notes": "x"})
        self.assertEqual(resp.status_code, 302)
        self.grade.refresh_from_db()
        wr.refresh_from_db()
        self.assertEqual(self.grade.marks, Decimal("55"))
        self.assertEqual(wr.status, "pending")  # left pending so admin can fix and retry


# ---------------------------------------------------------------------------
# Staged, separation-of-duties approvals
# ---------------------------------------------------------------------------
from governance.models import Role, RoleAssignment
from .models import WorkflowApproval


def _office(username, role_code):
    u = User.objects.create_user(username, password="pw")
    RoleAssignment.objects.create(user=u, role=Role.objects.get(code=role_code))
    return u


class StagedApprovalTests(WorkflowApprovalTests):
    def _fee_request(self, by):
        return WorkflowRequest.objects.create(
            request_type="fee_adjustment", requested_by=by, invoice=self.invoice,
            old_value="10000", new_value="8000", reason="Scholarship adjustment")

    def test_fee_adjustment_needs_review_then_manager_approval(self):
        fo = _office("fo1", "finance_officer")       # reviews (finance.reconcile)
        fm = _office("fm1", "finance_manager")       # approves (finance.approve)
        clerk = User.objects.create_user("clerk", password="pw")
        wr = self._fee_request(clerk)
        self.client.force_login(fm)                   # manager cannot skip the review stage
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 403)
        self.client.force_login(fo)
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 302)
        wr.refresh_from_db()
        self.assertEqual((wr.status, wr.current_stage), ("pending", 1))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal("10000"))      # nothing changed yet
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 403)  # not the manager
        self.client.force_login(fm)
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 302)
        wr.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(wr.status, "approved")
        self.assertEqual(self.invoice.amount, Decimal("8000"))
        self.assertEqual(wr.approvals.count(), 2)
        self.assertFalse(wr.break_glass)

    def test_requester_cannot_approve_their_own_request(self):
        fo = _office("fo2", "finance_officer")
        wr = self._fee_request(fo)
        self.client.force_login(fo)
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 403)

    def test_superuser_cannot_override_once_an_office_holder_exists(self):
        _office("fm2", "finance_manager")
        _office("fo3", "finance_officer")
        wr = self._fee_request(self.teacher_user if hasattr(self, "teacher_user") else self.admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 403)
        wr.refresh_from_db()
        self.assertEqual(wr.status, "pending")

    def test_break_glass_is_recorded_when_nobody_holds_the_authority(self):
        from core.models import AuditLog
        clerk = User.objects.create_user("clerk2", password="pw")
        wr = self._fee_request(clerk)
        self.client.force_login(self.admin)
        self.client.post(reverse("workflow-approve", args=[wr.pk]))
        wr.refresh_from_db()
        self.assertEqual(wr.status, "approved")
        self.assertTrue(wr.break_glass)
        self.assertTrue(AuditLog.objects.filter(action="BREAK_GLASS_APPROVAL").exists())

    def test_marks_correction_needs_department_then_controller(self):
        hod = _office("hod1", "hod")
        ctrl = _office("ctl1", "exam_controller")
        wr = WorkflowRequest.objects.create(request_type="marks_correction", requested_by=User.objects.get(username="teacher1"),
                                            grade_entry=self.grade, old_value="55", new_value="65", reason="Recount")
        self.client.force_login(ctrl)
        self.assertEqual(self.client.post(reverse("workflow-approve", args=[wr.pk])).status_code, 403)
        self.client.force_login(hod)
        self.client.post(reverse("workflow-approve", args=[wr.pk]))
        self.client.force_login(ctrl)
        self.client.post(reverse("workflow-approve", args=[wr.pk]))
        self.grade.refresh_from_db()
        self.assertEqual(self.grade.marks, Decimal("65"))

    def test_large_refund_adds_a_vice_chancellor_stage(self):
        from .chains import stages_for
        small = WorkflowRequest(request_type="refund", new_value="1000")
        big = WorkflowRequest(request_type="refund", new_value="90000")
        self.assertEqual(len(stages_for(big)), len(stages_for(small)) + 1)
        self.assertEqual(stages_for(big)[-1][1:], ("executive", "approve"))

    def test_user_with_no_authority_sees_no_approval_center(self):
        stranger = User.objects.create_user("nobody", password="pw")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("workflow-center")).status_code, 403)

    def test_rejection_is_recorded_and_final(self):
        fo = _office("fo4", "finance_officer")
        wr = self._fee_request(User.objects.create_user("clerk3", password="pw"))
        self.client.force_login(fo)
        self.client.post(reverse("workflow-reject", args=[wr.pk]))
        wr.refresh_from_db()
        self.assertEqual(wr.status, "rejected")
        self.assertEqual(wr.approvals.get().decision, "rejected")
