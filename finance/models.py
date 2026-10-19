from decimal import Decimal
import random
import string
from django.db import models
from django.utils import timezone

CATEGORY_CHOICES = [
    ('admission', 'Admission Fee'),
    ('semester', 'Semester Fee'),
    ('hostel', 'Hostel Fee'),
    ('transport', 'Transport Fee'),
    ('degree', 'Degree / Convocation Fee'),
    ('exam_fee', 'Examination Fee (legacy)'),
    ('library_fine', 'Library Fine'),
    ('penalty', 'Late Penalty'),
    ('exam_retake', 'Improvement / Retake Exam Fee'),
    ('other', 'Other'),
]

PAYMENT_METHOD_CHOICES = [
    ('bank_transfer', 'Bank Transfer'),
    ('jazzcash', 'JazzCash'),
    ('easypaisa', 'EasyPaisa'),
    ('card', 'Debit / Credit Card'),
    ('cash', 'Cash at Campus Office'),
]


def _generate_challan_no():
    stamp = timezone.now().strftime('%y%m%d')
    rand = ''.join(random.choices(string.digits, k=5))
    return f'UMS-{stamp}-{rand}'


class Invoice(models.Model):
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='invoices')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='semester')
    challan_no = models.CharField(max_length=40, unique=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=200, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    semester = models.ForeignKey('academics.Semester', null=True, blank=True, on_delete=models.SET_NULL, related_name='invoices', help_text='Set for per-semester fees so a student is never charged twice for the same semester.')

    def save(self, *args, **kwargs):
        if not self.challan_no:
            candidate = _generate_challan_no()
            while Invoice.objects.filter(challan_no=candidate).exists():
                candidate = _generate_challan_no()
            self.challan_no = candidate
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['student', 'paid']),
            models.Index(fields=['due_date', 'paid']),
            models.Index(fields=['category', 'paid']),
        ]

    @property
    def is_overdue(self):
        return bool(self.due_date and not self.paid and self.due_date < timezone.now().date())

    def __str__(self):
        return f'{self.challan_no} - {self.student.full_name} ({self.get_category_display()})'


class Payment(models.Model):
    STATUS_CHOICES = [('pending', 'Pending Verification'), ('confirmed', 'Confirmed')]
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, blank=True)
    transaction_id = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    paid_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['invoice'],
                condition=models.Q(status='pending'),
                name='uniq_pending_payment_per_invoice',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'paid_at']),
            models.Index(fields=['invoice', 'status']),
        ]

    def __str__(self):
        return f'{self.invoice.challan_no} - {self.amount} ({self.get_status_display()})'


class FeePolicy(models.Model):
    """Versioned fee rule scoped to a program/semester/student category."""
    name = models.CharField(max_length=160)
    program = models.ForeignKey('academics.Program', on_delete=models.CASCADE, null=True, blank=True, related_name='fee_policies')
    semester = models.ForeignKey('academics.Semester', on_delete=models.CASCADE, null=True, blank=True, related_name='fee_policies')
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    late_fee_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['name','version'], name='uniq_fee_policy_version')]


class FeeItem(models.Model):
    policy = models.ForeignKey(FeePolicy, on_delete=models.CASCADE, related_name='items')
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='semester')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['policy','code'], name='uniq_fee_policy_item_code')]


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    fee_item = models.ForeignKey(FeeItem, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    unit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    waiver_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    scholarship_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    late_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def net_amount(self):
        return max(Decimal('0'), self.quantity * self.unit_amount - self.waiver_amount - self.scholarship_amount + self.late_fee)


class PaymentTransaction(models.Model):
    STATUS_CHOICES = [('initiated','Initiated'),('pending','Pending'),('success','Success'),('failed','Failed'),('reversed','Reversed')]
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    provider = models.CharField(max_length=50)
    provider_reference = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Refund(models.Model):
    STATUS_CHOICES = [('requested','Requested'),('approved','Approved'),('processed','Processed'),('rejected','Rejected')]
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='refunds')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested')
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)


class Waiver(models.Model):
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='fee_waivers')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='waivers')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255)
    approved_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ScholarshipAdjustment(models.Model):
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='scholarship_adjustments')
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='scholarship_adjustments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    approved_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LedgerEntry(models.Model):
    ENTRY_CHOICES = [('debit','Debit'),('credit','Credit')]
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='ledger_entries')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    entry_type = models.CharField(max_length=10, choices=ENTRY_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReconciliationRecord(models.Model):
    provider = models.CharField(max_length=50)
    provider_reference = models.CharField(max_length=200)
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliations')
    status = models.CharField(max_length=30, default='matched')
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    reconciled_at = models.DateTimeField(auto_now_add=True)
