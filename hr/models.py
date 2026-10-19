from django.db import models
from django.contrib.auth.models import User

class Staff(models.Model):
    JOB_TITLE_CHOICES = [
        ('dean', 'Dean'),
        ('professor', 'Professor'),
        ('associate_professor', 'Associate Professor'),
        ('assistant_professor', 'Assistant Professor'),
        ('lecturer', 'Lecturer'),
        ('teaching_assistant', 'Teaching Assistant'),
        ('admin_officer', 'Admin Officer'),
        ('account_officer', 'Account Officer'),
        ('hostel_warden', 'Hostel Warden'),
        ('transport_manager', 'Transport Manager'),
        ('librarian', 'Librarian'),
        ('other', 'Other Staff'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    employee_id = models.CharField(max_length=100, unique=True)
    department = models.ForeignKey('academics.Department', on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=100, blank=True, choices=JOB_TITLE_CHOICES, help_text='Job title, e.g. Dean, Professor, Account Officer.')
    hire_date = models.DateField(null=True, blank=True)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    @property
    def full_name(self):
        name = self.user.get_full_name() or self.user.username
        # Registration/seed data sometimes ends up with inconsistent
        # casing (e.g. a properly-capitalized first name but a lowercase
        # last name, like "Muhammad ahmed") - normalize how the name is
        # DISPLAYED here rather than rewriting User.first_name/last_name
        # in the database, so this never touches login credentials or
        # anything else keyed off the raw stored value.
        return name.title() if name else name

    def __str__(self):
        return self.full_name


class Payroll(models.Model):
    """One month's salary payment for one staff/faculty member. Separate
    from student Invoices entirely - staff are paid, they never owe fees."""
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid')]

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='payslips')
    month = models.DateField(help_text='Any date within the salary month, e.g. 2026-08-01.')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reference = models.CharField(max_length=150, blank=True, help_text='Bank transfer reference / cheque no., etc.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('staff', 'month')]
        ordering = ['-month']

    def __str__(self):
        return f'{self.staff.full_name} - {self.month:%b %Y} ({self.get_status_display()})'

# a Staff record must never leave its login with the default "student" role - a new teacher
# would otherwise land on the student portal. Only the untouched default is changed; an existing
# admin/staff/faculty/guardian role is never overwritten.
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Staff)
def _sync_profile_role_from_staff(sender, instance, **kwargs):
    from core.models import Profile
    from core.services.accounts import profile_role_for_job
    Profile.objects.filter(user=instance.user_id, role='student').update(role=profile_role_for_job(instance.role))
