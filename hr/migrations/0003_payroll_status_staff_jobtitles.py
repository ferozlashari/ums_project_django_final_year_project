import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0002_alter_staff_user'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='staff',
            name='role',
            field=models.CharField(blank=True, choices=[('dean', 'Dean'), ('professor', 'Professor'), ('associate_professor', 'Associate Professor'), ('assistant_professor', 'Assistant Professor'), ('lecturer', 'Lecturer'), ('teaching_assistant', 'Teaching Assistant'), ('admin_officer', 'Admin Officer'), ('account_officer', 'Account Officer'), ('hostel_warden', 'Hostel Warden'), ('transport_manager', 'Transport Manager'), ('librarian', 'Librarian'), ('other', 'Other Staff')], help_text='Job title, e.g. Dean, Professor, Account Officer.', max_length=100),
        ),
        migrations.AddField(
            model_name='staff',
            name='monthly_salary',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='payroll',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('paid', 'Paid')], default='pending', max_length=10),
        ),
        migrations.AddField(
            model_name='payroll',
            name='paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payroll',
            name='paid_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='payroll',
            name='reference',
            field=models.CharField(blank=True, help_text='Bank transfer reference / cheque no., etc.', max_length=150),
        ),
        migrations.AddField(
            model_name='payroll',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='payroll',
            name='staff',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payslips', to='hr.staff'),
        ),
        migrations.AlterField(
            model_name='payroll',
            name='month',
            field=models.DateField(help_text='Any date within the salary month, e.g. 2026-08-01.'),
        ),
        migrations.AlterUniqueTogether(
            name='payroll',
            unique_together={('staff', 'month')},
        ),
        migrations.AlterModelOptions(
            name='payroll',
            options={'ordering': ['-month']},
        ),
    ]
