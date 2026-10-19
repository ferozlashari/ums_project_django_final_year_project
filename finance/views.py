from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import SiteSettings, notify
from core.permissions import admin_required, office_staff_required, user_role

from .forms import InvoiceForm, PaymentSubmitForm
from .models import Invoice, Payment


DEFAULT_BANK_DETAILS = {
    'bank_name': 'Not configured yet',
    'account_title': 'Not configured yet',
    'account_no': 'Not configured yet',
    'iban': 'Not configured yet',
    'jazzcash_number': 'Not configured yet',
    'easypaisa_number': 'Not configured yet',
}


def get_payment_details():
    settings = SiteSettings.load()
    details = DEFAULT_BANK_DETAILS.copy()
    mapping = {
        'bank_name': 'bank_name',
        'account_title': 'bank_account_title',
        'account_no': 'bank_account_no',
        'iban': 'bank_iban',
        'jazzcash_number': 'jazzcash_number',
        'easypaisa_number': 'easypaisa_number',
    }
    for public_name, field_name in mapping.items():
        value = getattr(settings, field_name, '')
        if value:
            details[public_name] = value
    return details


def _can_view_invoice(user, invoice):
    return user_role(user) != 'student' or invoice.student.user_id == user.id


def _student_for_user(user):
    return getattr(user, 'student_profile', None)


@login_required
@require_POST
def generate_my_challan(request, kind):
    """Self-service challan generation for every student-facing challan
    type. One generic view instead of one copy-pasted view per type -
    `kind` selects which FeeChallanService method to call, and every
    method already enforces its own eligibility rule and returns a
    ChallanResult, so this view stays identical no matter how many
    challan types get added later. This is also exactly what the AI
    assistant's action tools call, so a student gets the same answer
    whether they click the button or ask the assistant."""
    from .services import FeeChallanService
    method = {
        'semester': FeeChallanService.generate_semester_fee,
        'hostel': FeeChallanService.generate_hostel_fee,
        'transport': FeeChallanService.generate_transport_fee,
    }.get(kind)
    if method is None:
        raise PermissionDenied('Unknown challan type.')
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students can generate their own challans.')
    student = _student_for_user(request.user)
    if not student:
        messages.error(request, 'No student record is linked to this account. Please contact administration.')
        return redirect('fees-list')

    result = method(student)
    if not result.ok:
        messages.error(request, result.message)
        return redirect('fees-list')
    messages.success(request, result.message)
    return redirect('challan-detail', pk=result.invoice.pk)


@login_required
def fee_list(request):
    role = user_role(request.user)
    fees = Invoice.objects.select_related('student').order_by('-created_at')
    available_challans = []
    outstanding_total = paid_total = None
    if role == 'student':
        fees = fees.filter(student__user=request.user)
        student = _student_for_user(request.user)
        if student:
            from django.db.models import Sum
            outstanding_total = fees.filter(paid=False).aggregate(t=Sum('amount'))['t'] or 0
            paid_total = fees.filter(paid=True).aggregate(t=Sum('amount'))['t'] or 0
            from hostel.models import HostelApplication
            has_hostel_allocation = HostelApplication.objects.filter(
                student=student, status='approved', assigned_room__isnull=False,
            ).exists()
            has_transport_assignment = getattr(student, 'transport_assignment', None) is not None
            available_challans = [
                ('semester', 'Semester Fee'),
            ]
            if has_hostel_allocation:
                available_challans.append(('hostel', 'Hostel Fee'))
            if has_transport_assignment:
                available_challans.append(('transport', 'Transport Fee'))
    return render(request, 'core/fee-management.html', {
        'fees': fees, 'role': role, 'available_challans': available_challans,
        'outstanding_total': outstanding_total, 'paid_total': paid_total,
    })


@admin_required
def fee_add(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    invoice = form.save()
            except Exception:
                messages.error(request, 'The fee challan could not be generated. Please try again.')
            else:
                notify(
                    invoice.student.user,
                    f'New fee challan: {invoice.challan_no}',
                    f'{invoice.get_category_display()} challan of {invoice.amount} is due.',
                    level='warning',
                    url=reverse('challan-detail', kwargs={'pk': invoice.pk}),
                )
                messages.success(request, f'Challan {invoice.challan_no} generated successfully.')
                return redirect('challan-detail', pk=invoice.pk)
    else:
        initial = {key: request.GET[key] for key in ('student', 'category') if request.GET.get(key)}
        form = InvoiceForm(initial=initial)
    return render(request, 'core/form_base.html', {'form': form, 'title': 'Generate Fee Challan', 'cancel_url': reverse('fees-list')})


@login_required
def challan_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('student'), pk=pk)
    if not _can_view_invoice(request.user, invoice):
        raise PermissionDenied('You can only view your own challan.')
    return render(request, 'core/challan-detail.html', {'invoice': invoice, 'bank': get_payment_details(), 'role': user_role(request.user)})


@login_required
def pay_now(request, pk):
    if user_role(request.user) != 'student':
        raise PermissionDenied('Only students can submit payment references for their own challans.')

    invoice = get_object_or_404(Invoice.objects.select_related('student'), pk=pk)
    if not _can_view_invoice(request.user, invoice):
        raise PermissionDenied('You can only pay your own challan.')
    if invoice.paid:
        messages.info(request, 'This challan is already marked as paid.')
        return redirect('challan-detail', pk=pk)

    if request.method == 'POST':
        form = PaymentSubmitForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
                    if locked.paid:
                        messages.info(request, 'This challan has already been paid.')
                        return redirect('challan-detail', pk=pk)
                    payment = form.save(commit=False)
                    payment.invoice = locked
                    payment.amount = locked.amount
                    payment.status = 'pending'
                    payment.save()
            except IntegrityError:
                messages.info(request, 'A payment reference is already awaiting verification for this challan.')
                return redirect('challan-detail', pk=pk)
            except Exception:
                messages.error(request, 'We could not submit the payment reference. Please try again.')
                return redirect('challan-detail', pk=pk)
            messages.success(request, 'Payment reference submitted. It will be confirmed after accounts verification.')
            return redirect('challan-detail', pk=pk)
    else:
        form = PaymentSubmitForm()

    from .services_gateway import provider_for
    return render(request, 'core/pay-now.html', {
        'invoice': invoice, 'form': form, 'bank': get_payment_details(),
        'safepay_configured': provider_for('safepay').is_configured(),
    })


def _confirm_payment(payment_id, confirmed_by):
    """Shared, transaction-safe confirmation used by BOTH the office-staff
    manual "Confirm" button and the automatic Safepay webhook. Idempotent:
    calling it twice (e.g. a retried webhook) is a safe no-op the second time.
    Returns (invoice, payment) on success, or raises ValueError with a
    human-readable reason on failure - callers decide how to report that."""
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(pk=payment_id)
        except Payment.DoesNotExist:
            raise ValueError('The requested payment could not be found.')
        invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
        if payment.status == 'confirmed' or invoice.paid:
            return invoice, payment  # already done - idempotent, not an error
        if payment.status != 'pending':
            raise ValueError('Only pending payments can be confirmed.')
        payment.status = 'confirmed'
        payment.confirmed_at = timezone.now()
        payment.confirmed_by = confirmed_by
        payment.save(update_fields=['status', 'confirmed_at', 'confirmed_by'])
        invoice.paid = True
        invoice.save(update_fields=['paid'])
    return invoice, payment


@office_staff_required
@require_POST
def confirm_payment(request, payment_id):
    try:
        invoice, payment = _confirm_payment(payment_id, confirmed_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('pending-payments')
    except Exception:
        messages.error(request, 'The payment could not be confirmed. Please try again.')
        return redirect('pending-payments')

    from core.models import log_action
    log_action(
        request.user, 'PAYMENT_CONFIRMED', obj=f'{invoice.challan_no} ({invoice.student})',
        changes={'paid': ['False', 'True'], 'amount': [str(invoice.amount), str(invoice.amount)]},
        request=request,
    )
    notify(
        invoice.student.user,
        f'Payment confirmed: {invoice.challan_no}',
        f'Your payment of {payment.amount} has been verified.',
        level='success',
        url=reverse('challan-detail', kwargs={'pk': invoice.pk}),
    )
    messages.success(request, f'Payment for {invoice.challan_no} confirmed.')
    return redirect('challan-detail', pk=invoice.pk)


def _finish_online_payment(payment, source, request=None):
    """Confirm a Safepay payment (idempotent) and, only the first time,
    write the audit row + notify the student. `source` is 'redirect' or
    'webhook' so the audit trail shows which signed channel confirmed it."""
    was_confirmed = payment.status == 'confirmed'
    invoice, payment = _confirm_payment(payment.pk, confirmed_by=None)
    if was_confirmed:
        return invoice, payment
    from core.models import log_action
    from .models import PaymentTransaction
    PaymentTransaction.objects.filter(payment=payment).update(status='success')
    log_action(
        None, 'PAYMENT_CONFIRMED', obj=f'{invoice.challan_no} ({invoice.student})',
        changes={'paid': ['False', 'True'], 'channel': ['', f'safepay-{source}']},
        request=request,
    )
    notify(
        invoice.student.user, f'Payment received: {invoice.challan_no}',
        f'Your online payment of PKR {payment.amount} was received. Thank you.',
        level='success', url=reverse('challan-detail', kwargs={'pk': invoice.pk}),
    )
    return invoice, payment


@login_required
def gateway_checkout(request, pk):
    """Redirects the student's browser to the official Safepay hosted
    checkout page. Only usable once Safepay credentials are configured."""
    from .services_gateway import provider_for, create_payment
    invoice = get_object_or_404(Invoice.objects.select_related('student'), pk=pk)
    if not _can_view_invoice(request.user, invoice):
        raise PermissionDenied('You can only pay your own challan.')
    if invoice.paid:
        messages.info(request, 'This challan is already marked as paid.')
        return redirect('challan-detail', pk=pk)
    provider = provider_for('safepay')
    if not provider.is_configured():
        messages.error(request, 'Online card payment is not configured yet - use JazzCash, EasyPaisa, bank transfer, or cash below.')
        return redirect('pay-now', pk=pk)
    try:
        payment = create_payment(invoice, invoice.amount, 'safepay', idempotency_key=f'safepay-{invoice.pk}-{request.user.pk}')
        session = provider.initiate(
            payment,
            return_url=request.build_absolute_uri(reverse('gateway-return', args=[payment.pk])),
            cancel_url=request.build_absolute_uri(reverse('challan-detail', args=[invoice.pk])),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('pay-now', pk=pk)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Safepay checkout could not be created for invoice %s', pk)
        messages.error(request, 'Could not reach the Safepay payment gateway. Please try again, or use another payment method below.')
        return redirect('pay-now', pk=pk)
    return redirect(session['checkout_url'])


@login_required
def gateway_return(request, payment_id):
    """Where Safepay sends the browser after checkout.

    A plain GET is never trusted. The payment is confirmed here ONLY when the
    redirect carries `tracker` + `sig` and sig == HMAC-SHA256(shared secret,
    tracker) AND the tracker is the one we stored for this exact payment.
    This is what makes payments confirm on localhost, where Safepay's
    webhook cannot reach. On a hosted site the webhook confirms too;
    both paths are idempotent."""
    from .services_gateway import provider_for
    payment = get_object_or_404(Payment.objects.select_related('invoice__student'), pk=payment_id)
    if not _can_view_invoice(request.user, payment.invoice):
        raise PermissionDenied
    tracker = request.GET.get('tracker', '')
    sig = request.GET.get('sig', '')
    if payment.status != 'confirmed' and tracker and sig:
        stored = payment.transactions.filter(provider_reference=tracker).exists()
        if stored and provider_for('safepay').verify_redirect_signature(tracker, sig):
            try:
                _finish_online_payment(payment, 'redirect', request=request)
            except ValueError:
                pass
            payment.refresh_from_db()
    if payment.status == 'confirmed':
        messages.success(request, 'Payment confirmed - thank you!')
    else:
        messages.info(request, 'We have not received confirmation from Safepay yet. If you completed the payment, refresh this page in a minute.')
    return redirect('challan-detail', pk=payment.invoice_id)


@require_POST
def gateway_webhook(request):
    """Server-to-server Safepay webhook (CSRF-exempt in urls.py).
    Signature: header x-sfpy-signature = HMAC-SHA512(webhook secret,
    compact JSON of body["data"]). Only a notification whose state is PAID,
    whose amount equals what we asked Safepay to charge and whose tracker
    we issued is allowed to confirm a payment. Anything else is
    acknowledged (200) so Safepay does not retry forever, but changes
    nothing; amount mismatches are raised as an Exception Center item."""
    from .models import PaymentTransaction
    from .services_gateway import provider_for
    body = provider_for('safepay').verify_webhook(
        request.body, request.headers.get('x-sfpy-signature', ''))
    if body is None:
        return HttpResponse(status=400)
    data = body.get('data', body) if isinstance(body, dict) else {}
    note = data.get('notification', data) if isinstance(data, dict) else {}
    tracker = str(note.get('tracker') or '')
    txn = PaymentTransaction.objects.select_related('payment').filter(provider_reference=tracker).first() if tracker else None
    if txn is None:
        return HttpResponse(status=200)
    txn.response_payload = body if isinstance(body, dict) else {}
    txn.save(update_fields=['response_payload', 'updated_at'])
    if str(note.get('state', '')).upper() != 'PAID':
        return HttpResponse(status=200)
    payment = txn.payment
    try:
        paid_amount = Decimal(str(note.get('amount', '')))
    except Exception:
        paid_amount = None
    if paid_amount != payment.amount or str(note.get('currency', 'PKR')).upper() != 'PKR':
        from core.models import ExceptionRecord
        ExceptionRecord.objects.create(
            code='PAYMENT_AMOUNT_MISMATCH', severity='critical', module='finance',
            message=f'Safepay reported {note.get("amount")} {note.get("currency")} for payment {payment.pk}, expected PKR {payment.amount}.',
            object_type='Payment', object_id=str(payment.pk), details={'tracker': tracker},
        )
        txn.status = 'failed'
        txn.save(update_fields=['status', 'updated_at'])
        return HttpResponse(status=200)
    try:
        _finish_online_payment(payment, 'webhook', request=request)
    except ValueError:
        pass
    return HttpResponse(status=200)


@admin_required
@require_POST
def apply_late_fee(request, pk):
    from .services import FeeChallanService
    invoice = get_object_or_404(Invoice, pk=pk)
    result = FeeChallanService.issue_late_fee(invoice)
    if result.ok:
        messages.success(request, result.message)
        return redirect('challan-detail', pk=result.invoice.pk)
    messages.info(request, result.message)
    return redirect('challan-detail', pk=(result.invoice.pk if result.invoice else pk))


@office_staff_required
def pending_payments(request):
    payments = Payment.objects.filter(status='pending').select_related('invoice', 'invoice__student').order_by('paid_at')
    return render(request, 'core/pending-payments.html', {'payments': payments})


VERIFY_CHALLAN_MAX_LOOKUPS = 30        # per visitor
VERIFY_CHALLAN_WINDOW_SECONDS = 600


def verify_challan(request):
    challan_no = request.GET.get('challan_no', '').strip()[:40]
    invoice = None
    searched = bool(challan_no)
    if challan_no:
        # Public page: limit lookups per visitor so challan numbers cannot be guessed in bulk.
        from django.core.cache import cache
        key = f"verify_challan:{request.META.get('REMOTE_ADDR', 'unknown')}"
        used = cache.get(key, 0)
        if used >= VERIFY_CHALLAN_MAX_LOOKUPS:
            return render(request, 'core/verify-challan.html',
                          {'challan_no': '', 'invoice': None, 'searched': False,
                           'throttled': True}, status=429)
        cache.set(key, used + 1, VERIFY_CHALLAN_WINDOW_SECONDS)
        invoice = Invoice.objects.filter(challan_no__iexact=challan_no).select_related('student').first()
    return render(request, 'core/verify-challan.html', {'challan_no': challan_no, 'invoice': invoice, 'searched': searched})
