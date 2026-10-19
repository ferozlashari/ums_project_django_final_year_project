from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0004_integrity_indexes')]
    operations = [
        migrations.AddIndex(model_name='invoice', index=models.Index(fields=['student', 'paid'], name='finance_in_student_1e2c4f_idx')),
        migrations.AddIndex(model_name='invoice', index=models.Index(fields=['due_date', 'paid'], name='finance_in_due_dat_4f7a9e_idx')),
        migrations.AddIndex(model_name='invoice', index=models.Index(fields=['category', 'paid'], name='finance_in_categor_7b2d1c_idx')),
    ]
