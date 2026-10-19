from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from finance.models import Invoice, Payment


class FeeEligibilityService:
    CATEGORIES = {
        'semester': 'Semester tuition', 'admission': 'Admission fee', 'exam_retake': 'Retake/improvement fee',
        'library_fine': 'Library fine', 'hostel': 'Hostel fee', 'penalty': 'Late penalty', 'other': 'Institutional fee',
    }
    @classmethod
    def unpaid(cls, student):
        return Invoice.objects.filter(student=student, paid=False).order_by('due_date', 'created_at')

    @classmethod
    def can_create(cls, student, category, reference=''):
        if not student or student.status != 'active': return False, 'Student account is not active.'
        if category not in cls.CATEGORIES: return False, 'Unsupported fee category.'
        qs = Invoice.objects.filter(student=student, category=category, paid=False)
        if reference: qs = qs.filter(reference=reference)
        if qs.exists(): return False, 'An unpaid challan for this service already exists.'
        return True, ''


class PaymentService:
    @staticmethod
    @transaction.atomic
    def submit(invoice_id, amount, method, transaction_id):
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        if invoice.paid: raise ValueError('This challan is already paid.')
        if Payment.objects.filter(invoice=invoice, status='pending').exists(): raise ValueError('A payment is already awaiting verification.')
        if Decimal(str(amount)) != invoice.amount: raise ValueError('Payment amount does not match the challan.')
        if not transaction_id or len(transaction_id.strip()) < 3: raise ValueError('A valid payment reference is required.')
        return Payment.objects.create(invoice=invoice, amount=invoice.amount, method=method, transaction_id=transaction_id.strip(), status='pending')

    @staticmethod
    @transaction.atomic
    def confirm(payment_id, user):
        payment = Payment.objects.select_for_update().select_related('invoice').get(pk=payment_id)
        invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
        if invoice.paid or payment.status == 'confirmed': return payment, invoice
        if payment.status != 'pending': raise ValueError('Only pending payments can be confirmed.')
        payment.status = 'confirmed'; payment.confirmed_by = user; payment.confirmed_at = timezone.now(); payment.save(update_fields=['status','confirmed_by','confirmed_at'])
        invoice.paid = True; invoice.save(update_fields=['paid'])
        return payment, invoice
