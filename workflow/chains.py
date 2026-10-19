"""Approval chains: who must decide, in what order, for each request type.

Every stage is a (label, governance module, governance action). The person who
decides a stage must hold that permission (scoped to the program where one can
be derived), cannot be the person who raised the request, and cannot also have
decided an earlier stage of the same request.
"""
from decimal import Decimal, InvalidOperation

CHAINS = {
    "marks_correction": [
        ("Department review", "results", "verify"),
        ("Controller of Examinations", "results", "override"),
    ],
    "fee_adjustment": [
        ("Finance review", "finance", "reconcile"),
        ("Finance Manager approval", "finance", "approve"),
    ],
    "refund": [
        ("Finance review", "finance", "reconcile"),
        ("Finance Manager approval", "finance", "approve"),
    ],
    "other": [
        ("Registrar approval", "registration", "approve"),
    ],
}

REFUND_EXECUTIVE_LIMIT = Decimal("50000")   # PKR; above this a VC-level approval is added


def stages_for(wr):
    stages = list(CHAINS.get(wr.request_type, CHAINS["other"]))
    if wr.request_type == "refund":
        try:
            amount = Decimal(wr.new_value or "0")
        except InvalidOperation:
            amount = Decimal("0")
        if amount > REFUND_EXECUTIVE_LIMIT:
            stages.append(("Vice Chancellor (large refund)", "executive", "approve"))
    return stages


def program_scope(wr):
    """The program a request is about, when it can be derived (for scoped roles)."""
    try:
        if wr.grade_entry_id:
            return wr.grade_entry.exam.course.program
        if wr.invoice_id:
            return wr.invoice.student.active_program
    except Exception:
        return None
    return None
