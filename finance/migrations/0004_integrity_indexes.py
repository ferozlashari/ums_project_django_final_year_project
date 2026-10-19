from django.db import migrations, models
from django.db.models import Q


def cleanup(apps, schema_editor):
    Model = apps.get_model('finance', 'Payment')
    seen = set()
    for row in Model.objects.filter(status='pending').order_by('invoice_id', '-paid_at', '-id'):
        if row.invoice_id in seen:
            row.delete()
        else:
            seen.add(row.invoice_id)


class Migration(migrations.Migration):
    dependencies = [('finance', '0003_alter_invoice_category')]
    operations = [
        migrations.RunPython(cleanup, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='payment', constraint=models.UniqueConstraint(condition=Q(status='pending'), fields=('invoice',), name='uniq_pending_payment_per_invoice')),
        migrations.AddIndex(model_name='payment', index=models.Index(fields=['status', 'paid_at'], name='finance_pa_status_6a7f0d_idx')),
        migrations.AddIndex(model_name='payment', index=models.Index(fields=['invoice', 'status'], name='finance_pa_invoice_3c6b7e_idx')),
    ]
