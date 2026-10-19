from django.contrib import admin
from .models import Invoice, Payment


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('challan_no', 'student', 'category', 'amount', 'due_date', 'paid', 'is_overdue')
    list_filter = ('category', 'paid')
    search_fields = ('challan_no', 'student__full_name', 'student__admission_no', 'reference')
    readonly_fields = ('challan_no',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'amount', 'method', 'status', 'paid_at')
    list_filter = ('method', 'status')

from .models import FeePolicy, FeeItem, InvoiceLine, PaymentTransaction, Refund, Waiver, ScholarshipAdjustment, LedgerEntry, ReconciliationRecord
admin.site.register([FeePolicy, FeeItem, InvoiceLine, PaymentTransaction, Refund, Waiver, ScholarshipAdjustment, LedgerEntry, ReconciliationRecord])
