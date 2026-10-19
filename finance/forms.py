from django import forms
from .models import Invoice, Payment


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['student', 'category', 'amount', 'due_date', 'reference', 'notes']
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'})}


class PaymentSubmitForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['method', 'transaction_id']
        widgets = {
            'transaction_id': forms.TextInput(attrs={'placeholder': 'Transaction / receipt reference (optional)'}),
        }
