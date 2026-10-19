from django.db import migrations, models
from django.db.models import Q


def cleanup(apps, schema_editor):
    Model = apps.get_model('library', 'BookLoan')
    seen = set()
    for row in Model.objects.filter(status='borrowed').order_by('student_id', 'book_id', '-borrowed_at', '-id'):
        key = (row.book_id, row.student_id)
        if key in seen:
            row.status = 'returned'
            row.returned_at = row.borrowed_at
            row.save(update_fields=['status', 'returned_at'])
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [('library', '0005_book_added_by')]
    operations = [
        migrations.RunPython(cleanup, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='bookloan', constraint=models.UniqueConstraint(condition=Q(status='borrowed'), fields=('book', 'student'), name='uniq_active_book_loan')),
        migrations.AddIndex(model_name='bookloan', index=models.Index(fields=['student', 'status'], name='library_b_student_5f9a1b_idx')),
        migrations.AddIndex(model_name='bookloan', index=models.Index(fields=['book', 'status'], name='library_b_book_7c6c8e_idx')),
        migrations.AddIndex(model_name='bookloan', index=models.Index(fields=['due_date', 'status'], name='library_b_due_dat_2f9a0b_idx')),
    ]
