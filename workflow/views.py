from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import log_action
from core.permissions import user_role
from .forms import WorkflowRequestForm
from governance.permissions import authority_perm, has_perm
from .chains import program_scope, stages_for
from .models import WorkflowApproval, WorkflowRequest


@login_required
def submit_request(request):
    role = user_role(request.user)
    if role not in ("faculty", "staff", "admin"):
        raise PermissionDenied("Only faculty, staff, or admin can submit a workflow request.")
    if request.method == "POST":
        form = WorkflowRequestForm(request.POST, role=role, user=request.user)
        if form.is_valid():
            wr = form.save(commit=False)
            wr.requested_by = request.user
            wr.status = "pending"
            wr.save()
            log_action(request.user, "WORKFLOW_REQUESTED", obj=wr, request=request)
            messages.success(request, "Your request has been submitted for approval.")
            return redirect("my-workflow-requests")
    else:
        form = WorkflowRequestForm(role=role, user=request.user)
    return render(request, "core/form_base.html", {
        "form": form, "title": "Request an Approval (marks correction, fee adjustment, exception)",
        "cancel_url": "/dashboard/",
    })


@login_required
def my_requests(request):
    requests_qs = WorkflowRequest.objects.filter(requested_by=request.user).select_related(
        "grade_entry", "invoice", "decided_by"
    )
    return render(request, "workflow/my-requests.html", {"requests": requests_qs})


def _stage_info(wr):
    stages = stages_for(wr)
    if wr.current_stage >= len(stages):
        return None, stages
    return stages[wr.current_stage], stages


def can_decide(user, wr):
    """(allowed, break_glass, reason_if_not) for `user` at wr's current stage."""
    stage, _ = _stage_info(wr)
    if stage is None or wr.status != "pending":
        return False, False, "This request is already decided."
    label, module, action = stage
    ok, glass = authority_perm(user, module, action, program=program_scope(wr))
    if not ok:
        return False, False, f"Stage \"{label}\" needs the {module}.{action} permission."
    if not glass:
        if wr.requested_by_id == user.pk:
            return False, False, "You raised this request, so someone else must decide it (separation of duties)."
        if wr.approvals.filter(decided_by=user).exists():
            return False, False, "You already decided an earlier stage - a different person must decide this one."
    return True, glass, ""


def _actionable_for(user):
    """Pending requests this user may decide right now, as (request, stage_label) pairs."""
    out = []
    for wr in WorkflowRequest.objects.filter(status="pending").select_related("requested_by", "grade_entry", "invoice"):
        ok, _, _ = can_decide(user, wr)
        if ok:
            out.append((wr, _stage_info(wr)[0][0]))
    return out


def _is_overseer(user):
    return user.is_superuser or has_perm(user, "audit", "view") or has_perm(user, "executive", "view")


@login_required
def workflow_center(request):
    mine = _actionable_for(request.user)
    overseer = _is_overseer(request.user)
    if not mine and not overseer:
        raise PermissionDenied("You have no approvals waiting. Requests you raised are under 'My Approval Requests'.")
    pending_all = WorkflowRequest.objects.filter(status="pending").select_related("requested_by", "grade_entry", "invoice")
    decided = WorkflowRequest.objects.exclude(status="pending").select_related(
        "requested_by", "decided_by", "grade_entry", "invoice")[:25]
    rows = []
    actionable_ids = {wr.pk for wr, _ in mine}
    for wr in pending_all:
        stage, stages = _stage_info(wr)
        rows.append({"r": wr, "stage": stage[0] if stage else "", "step": f"{wr.current_stage + 1} of {len(stages)}",
                     "can": wr.pk in actionable_ids, "history": list(wr.approvals.all())})
    return render(request, "workflow/center.html", {
        "rows": rows if overseer else [x for x in rows if x["can"]], "decided": decided, "overseer": overseer,
        "pending": [x["r"] for x in rows]})


def _notify_next(wr):
    stage, _ = _stage_info(wr)
    if stage:
        label, module, action = stage
        from governance.models import RoleAssignment
        from core.models import notify
        holders = {a.user for a in RoleAssignment.objects.filter(
            is_active=True, user__is_active=True, role__permissions__module=module, role__permissions__action=action
        ).select_related("user").distinct() if a.is_current()}
        for u in holders:
            if u.pk != wr.requested_by_id:
                notify(u, "Approval waiting", f"{wr.get_request_type_display()} #{wr.pk} is waiting at: {label}.",
                       level="info", url="/workflow/center/")


def _apply(request, wr):
    """Run the real change once the whole chain has approved."""
    detail = ""
    if wr.request_type == "marks_correction" and wr.grade_entry_id and wr.new_value:
        try:
            new_marks = Decimal(wr.new_value)
        except InvalidOperation:
            return None, f"'{wr.new_value}' isn't a valid marks value."
        entry = wr.grade_entry
        old_marks = entry.marks
        entry.marks = new_marks
        entry.admin_unlocked = True
        entry.save(update_fields=["marks", "admin_unlocked"])
        log_action(request.user, "GRADE_UPDATED", obj=f"{entry.student} / {entry.exam}",
                   changes={"marks": [str(old_marks), str(new_marks)]},
                   reason=f"Approved workflow request #{wr.pk}: {wr.reason}", request=request)
        detail = f"Marks updated from {old_marks} to {new_marks}."
    elif wr.request_type == "fee_adjustment" and wr.invoice_id and wr.new_value:
        try:
            new_amount = Decimal(wr.new_value)
        except InvalidOperation:
            return None, f"'{wr.new_value}' isn't a valid amount."
        invoice = wr.invoice
        old_amount = invoice.amount
        invoice.amount = new_amount
        invoice.save(update_fields=["amount"])
        log_action(request.user, "INVOICE_ADJUSTED", obj=invoice,
                   changes={"amount": [str(old_amount), str(new_amount)]},
                   reason=f"Approved workflow request #{wr.pk}: {wr.reason}", request=request)
        detail = f"Invoice amount updated from PKR {old_amount} to PKR {new_amount}."
    elif wr.request_type == "refund":
        # Approval only: the cashier posts the actual reversal, so money never
        # moves from a single click.
        detail = "Refund approved - the Cashier/Finance Officer may now post the reversal."
    return detail, ""


@login_required
@require_POST
def approve_request(request, pk):
    wr = get_object_or_404(WorkflowRequest, pk=pk, status="pending")
    ok, glass, why = can_decide(request.user, wr)
    if not ok:
        raise PermissionDenied(why)
    notes = request.POST.get("notes", "")
    stages = stages_for(wr)
    with transaction.atomic():
        # Break-glass (no office holder exists): the System Administrator completes the whole chain, loudly.
        last_stage = len(stages) - 1 if glass else wr.current_stage
        for i in range(wr.current_stage, last_stage + 1):
            WorkflowApproval.objects.create(request=wr, stage=i, stage_label=stages[i][0], decided_by=request.user,
                                            decision="approved", notes=notes, break_glass=glass)
        wr.current_stage = last_stage + 1
        if wr.current_stage < len(stages):
            wr.save(update_fields=["current_stage"])
            log_action(request.user, "WORKFLOW_STAGE_APPROVED", obj=wr, reason=notes, request=request)
            _notify_next(wr)
            messages.success(request, f"Stage approved. Now waiting for: {stages[wr.current_stage][0]}.")
            return redirect("workflow-center")
        detail, err = _apply(request, wr)
        if err:
            transaction.set_rollback(True)
            messages.error(request, f"Can't apply: {err}")
            return redirect("workflow-center")
        wr.status = "approved"
        wr.decided_by, wr.decided_at, wr.decision_notes = request.user, timezone.now(), notes
        wr.break_glass = glass
        wr.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "current_stage", "break_glass"])
    log_action(request.user, "BREAK_GLASS_APPROVAL" if glass else "WORKFLOW_APPROVED", obj=wr, reason=notes, request=request)
    if wr.requested_by_id:
        from core.models import notify
        notify(wr.requested_by, "Workflow request approved", detail or "Your request was approved.", level="success", url="/workflow/mine/")
    messages.success(request, f"Approved. {detail}".strip())
    return redirect("workflow-center")


@login_required
@require_POST
def reject_request(request, pk):
    wr = get_object_or_404(WorkflowRequest, pk=pk, status="pending")
    ok, glass, why = can_decide(request.user, wr)
    if not ok:
        raise PermissionDenied(why)
    notes = request.POST.get("notes", "")
    stage = _stage_info(wr)[0]
    WorkflowApproval.objects.create(request=wr, stage=wr.current_stage, stage_label=stage[0], decided_by=request.user,
                                    decision="rejected", notes=notes, break_glass=glass)
    wr.status = "rejected"
    wr.decided_by, wr.decided_at, wr.decision_notes = request.user, timezone.now(), notes
    wr.save(update_fields=["status", "decided_by", "decided_at", "decision_notes"])
    log_action(request.user, "WORKFLOW_REJECTED", obj=wr, reason=notes, request=request)
    if wr.requested_by_id:
        from core.models import notify
        notify(wr.requested_by, "Workflow request rejected", notes or "Your request was not approved.", level="warning", url="/workflow/mine/")
    messages.info(request, "Request rejected.")
    return redirect("workflow-center")
