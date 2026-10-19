from django.db import models
from django.contrib.auth.models import User

class Campus(models.Model):
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=300, blank=True)
    def __str__(self): return self.name
    class Meta:
        verbose_name_plural = 'Campuses'

class Profile(models.Model):
    ROLE_CHOICES = [('student','Student'),('faculty','Faculty'),('staff','Staff'),('admin','Admin'),('guardian','Parent/Guardian')]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    photo = models.ImageField(upload_to='profiles/', null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    campus = models.ForeignKey(Campus, on_delete=models.SET_NULL, null=True, blank=True)
    # Notification preferences (account settings, available to every role)
    notify_email_notices = models.BooleanField(default=True, verbose_name='Email me about new notices')
    notify_email_fees = models.BooleanField(default=True, verbose_name='Email me about fee challans and due dates')
    notify_email_complaints = models.BooleanField(default=True, verbose_name='Email me about complaint status updates')
    two_factor_enabled = models.BooleanField(default=False, verbose_name='Require passkey verification at login')
    # Deliberately a SEPARATE toggle from two_factor_enabled above: 2FA at
    # login and biometric attendance check-in both use the same registered
    # WebAuthn device(s), but are independent features - a student might
    # want fingerprint check-in for attendance without requiring it every
    # time they log in, or vice versa.
    biometric_attendance_enabled = models.BooleanField(
        default=True,
        verbose_name='Show passkey "Verify & Check In" option on attendance, exams, and online classes',
    )
    # Accessibility & outreach preferences
    high_contrast_mode = models.BooleanField(default=False, verbose_name='High-contrast, larger-text display')
    text_only_mode = models.BooleanField(default=False, verbose_name='Low-bandwidth text-only layout (hides images/charts)')
    sms_fallback_number = models.CharField(
        max_length=20, blank=True,
        verbose_name='SMS fallback number',
        help_text='Critical alerts are queued locally for delivery through an institution-managed SMS gateway if one is configured.',
    )
    def __str__(self): return self.user.username


class WebAuthnCredential(models.Model):
    """A registered fingerprint/face/security-key credential (WebAuthn/FIDO2).
    The actual biometric data never leaves the user's device or reaches this
    server - only a public key and a device-generated credential ID are
    stored, exactly like passkeys on any major site."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='webauthn_credentials')
    credential_id = models.CharField(max_length=255, unique=True)
    public_key = models.TextField()
    sign_count = models.PositiveIntegerField(default=0)
    device_name = models.CharField(max_length=100, default='My device')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.device_name} ({self.user.username})'


class Notice(models.Model):
    title = models.CharField(max_length=255)
    body = models.TextField()
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.title


class Notification(models.Model):
    """A single in-app notification for one user, generated automatically
    when something relevant happens elsewhere in the system (a grade is
    posted, a fee challan is issued, a complaint is updated, a hostel
    application is decided, a book is due soon, and so on). Shown as a
    bell/badge next to Logout in the header."""
    LEVEL_CHOICES = [('info', 'Info'), ('success', 'Success'), ('warning', 'Warning'), ('danger', 'Danger')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=500, blank=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    url = models.CharField(max_length=300, blank=True, help_text='Where clicking the notification should go')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} -> {self.user.username}'


def notify(user, title, message='', level='info', url='', email=False):
    """Create a Notification for a single user. Never raises - a broken
    notification must never break the action that triggered it. Also
    queues an SMS fallback for warning/danger-level alerts if the user has
    opted in a phone number (Accessibility & Outreach layer)."""
    if user is None:
        return None
    try:
        note = Notification.objects.create(user=user, title=title, message=message, level=level, url=url)
        if email or level in ('warning', 'danger'):
            try:
                from core.emailing import send_notification_email
                send_notification_email(user, title, message, url)
            except Exception:
                pass
        if level in ('warning', 'danger'):
            try:
                profile = user.profile
                if profile.sms_fallback_number:
                    SMSOutboxMessage.objects.create(
                        user=user, phone_number=profile.sms_fallback_number,
                        message=f'{title}: {message}'[:320],
                    )
            except Exception:
                pass
        return note
    except Exception:
        return None


def notify_many(users, title, message='', level='info', url=''):
    """Create the same notification for a list/queryset of users, in one query."""
    try:
        objs = [Notification(user=u, title=title, message=message, level=level, url=url) for u in users if u is not None]
        return Notification.objects.bulk_create(objs)
    except Exception:
        return []


class SiteSettings(models.Model):
    """Singleton: site-wide options an admin can change from the web UI
    instead of editing .env or code. Always use SiteSettings.load() to get
    the single active row (creates it with defaults on first use)."""
    site_name = models.CharField(max_length=100, default='UMS', help_text='Short name/abbreviation shown in the sidebar logo and browser tab.')
    site_full_name = models.CharField(max_length=255, default='University Management System', help_text='Full institution/system name shown in the page header alongside the short name - e.g. "University of Sindh - University Management System".')
    site_tagline = models.CharField(max_length=255, blank=True, default='Campus operations, simplified.')
    contact_email = models.EmailField(blank=True)
    currency_symbol = models.CharField(max_length=10, default='Rs.')
    allow_public_registration = models.BooleanField(default=True)
    allow_public_admissions = models.BooleanField(default=True)
    enable_guardian_portal = models.BooleanField(default=False, help_text='Optional extension. Off by default: guardian details are kept on the student record, and a separate Parent/Guardian login is only offered when the university needs it.')
    maintenance_mode = models.BooleanField(default=False, help_text='When on, only staff/admin can log in - everyone else sees a maintenance notice.')
    maintenance_message = models.CharField(max_length=255, blank=True, default='UMS is temporarily down for maintenance. Please check back soon.')
    # Payment details - editable per institution so any campus deploying this
    # app can plug in its own real bank/JazzCash/EasyPaisa accounts without
    # touching code. Shown on the "Pay Now" and challan pages.
    bank_name = models.CharField(max_length=150, blank=True, default='')
    bank_account_title = models.CharField(max_length=150, blank=True, default='')
    bank_account_no = models.CharField(max_length=60, blank=True, default='')
    bank_iban = models.CharField(max_length=40, blank=True, default='')
    jazzcash_number = models.CharField(max_length=20, blank=True, default='', verbose_name='JazzCash mobile account number')
    easypaisa_number = models.CharField(max_length=20, blank=True, default='', verbose_name='EasyPaisa mobile account number')
    # AI Assistant provider - switch without touching .env or redeploying.
    # Local is the zero-cost default. Optional free-tier providers may be
    # enabled by an institution, but the core system never depends on them.
    LLM_PROVIDER_CHOICES = [
        ('local', 'Built-in Local Assistant (zero cost)'),
        ('groq', 'Groq (optional free tier)'),
        ('huggingface', 'Hugging Face (optional free tier)'),
        ('gemini', 'Google Gemini (optional free tier)'),
    ]
    llm_provider = models.CharField(max_length=20, choices=LLM_PROVIDER_CHOICES, default='local')
    # Attendance policy - institution-wide, separate from each user's own
    # biometric_attendance_enabled preference above. If ON, the plain
    # "Check In Now" button is hidden campus-wide and only the
    # passkey-verified option is offered.
    require_biometric_attendance = models.BooleanField(
        default=False,
        verbose_name='Require passkey verification for attendance (hide plain self check-in)',
    )
    # Institution-wide academic/finance policy controls used by deterministic services.
    minimum_attendance_percent = models.DecimalField(max_digits=5, decimal_places=2, default=80)
    max_registration_credits = models.PositiveSmallIntegerField(default=21)
    default_drop_window_days = models.PositiveSmallIntegerField(default=14,
        help_text='When a semester has no drop deadline and no registration close date, students may drop a course until this many days after the semester starts.')
    admission_waitlist_buffer = models.PositiveSmallIntegerField(default=20,
        help_text='For an applicant\'s LAST-choice preference only: if not selected but their merit rank is within this many places past the seat cutoff, they show as Waiting List instead of Not Allocated.')
    merit_entry_test_weight = models.PositiveSmallIntegerField(default=100,
        help_text='Percent of the merit score that comes from the entry test (the rest comes from the previous qualification percentage). 100 = entry test only.')
    probation_cgpa_threshold = models.DecimalField(max_digits=3, decimal_places=2, default=2.00,
        help_text='CGPA below this places a student on Academic Probation.')
    honor_cgpa_threshold = models.DecimalField(max_digits=3, decimal_places=2, default=3.50,
        help_text='CGPA at or above this places a student on the Honor Roll.')
    block_registration_on_overdue_fees = models.BooleanField(
        default=False,
        help_text='When enabled, a student with any unpaid, overdue fee challan cannot register for new courses until it is cleared.',
    )
    max_retake_attempts = models.PositiveSmallIntegerField(default=2)
    max_improvement_attempts = models.PositiveSmallIntegerField(default=1)
    retake_window_years = models.PositiveSmallIntegerField(
        default=2,
        help_text='A student may only apply to retake/improve a subject within this many years of the grade being recorded - after that, the window closes and they must contact administration.',
    )
    late_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    hostel_annual_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=95000,
        help_text='Hostel fee charged once per academic year (not per semester) to students with an approved room allocation - used by student self-service hostel challan generation.',
    )
    retake_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=5000, help_text='Fee charged for a retake (failed course) exam application.')
    improvement_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=2500, help_text='Fee charged for an improvement (passed with a weak grade) exam application.')
    marks_lock_days = models.PositiveSmallIntegerField(
        default=60,
        help_text='Days after a grade is first entered before it automatically locks for teachers (an admin can still override a specific entry).',
    )

    # Security controls - admin-configurable so a lockdown response doesn't
    # need a code change/redeploy. Login throttling defaults still come
    # from .env (LOGIN_THROTTLE_MAX_ATTEMPTS) for the very first request
    # before this row exists; once set here, these values win.
    max_login_attempts = models.PositiveSmallIntegerField(
        default=5, verbose_name='Max failed login attempts before temporary lockout',
    )
    login_lockout_minutes = models.PositiveSmallIntegerField(
        default=5, verbose_name='Lockout duration (minutes) after too many failed logins',
    )
    require_2fa_for_admin = models.BooleanField(
        default=False,
        verbose_name='Require passkey 2FA for all admin accounts (blocks admin login without a registered device)',
    )
    session_timeout_minutes = models.PositiveIntegerField(
        default=480, verbose_name='Auto-logout after this many minutes of inactivity (default 480 = 8 hours)',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return 'Site Settings'

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SMSOutboxMessage(models.Model):
    """A queued SMS - the 'SMS fallback' piece of the Accessibility &
    Outreach layer, for users who opt in an sms_fallback_number but don't
    reliably check email/the app. Messages are queued here until an
    institution-managed SMS gateway is connected; the queue table does not
    change when that happens."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sms_outbox')
    phone_number = models.CharField(max_length=20)
    message = models.CharField(max_length=320)
    created_at = models.DateTimeField(auto_now_add=True)
    sent = models.BooleanField(default=False, help_text='Set True once a real SMS gateway is wired in and confirms delivery.')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'SMS to {self.phone_number}: {self.message[:40]}'


class AuditLog(models.Model):
    """A generic, append-only record of sensitive actions across the
    system - who did what, to which record, when, and what changed.
    Deliberately generic (actor + action string + a JSON before/after
    diff) rather than one table per module, so any view can log an event
    with a single log_action() call instead of a bespoke model. Records
    are never updated or deleted through the application - only ever
    created - and Django admin (see AuditLogAdmin) disables add/change/
    delete entirely so even a superuser can't quietly edit history."""
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_actions', help_text='Null for system/automation-triggered actions with no human actor.')
    action = models.CharField(max_length=100, help_text="e.g. 'GRADE_UPDATED', 'PAYMENT_CONFIRMED', 'RETAKE_APPROVED'")
    object_repr = models.CharField(max_length=255, blank=True, help_text='Human-readable description of the affected record.')
    changes = models.JSONField(default=dict, blank=True, help_text='{"field": [old_value, new_value]} - empty for actions with no field-level diff (e.g. a login).')
    reason = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['action', '-created_at'])]

    def __str__(self):
        who = self.actor.username if self.actor else 'system'
        return f'{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.object_repr}'


def _json_safe(value):
    """Recursively normalize a value so it's guaranteed to survive
    JSONField serialization - Decimal/date/datetime/UUID/model instances
    and anything else json.dumps doesn't natively support all get turned
    into a plain string, instead of quietly taking down the whole audit
    entry (see log_action's own defensive try/except below, and the
    project's earlier history with 'Object of type X is not JSON
    serializable' errors in audit logging)."""
    import datetime
    import decimal
    import uuid

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (decimal.Decimal, datetime.date, datetime.datetime, datetime.time, uuid.UUID)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, models.Model):
        return str(value)
    # Fallback for anything else (custom objects, QuerySets, etc.)
    try:
        import json
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def log_action(actor, action, obj=None, changes=None, reason='', request=None):
    """Record one audit entry. Never raises - a broken audit call must
    never block the actual action it's describing. `changes` should be
    {"field": [old, new]} for the fields that actually changed. Values in
    `changes` are normalized via _json_safe() first, so passing a Decimal,
    date, or model instance by mistake degrades to its string form rather
    than silently dropping the entire audit entry."""
    try:
        ip = None
        if request is not None:
            ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        AuditLog.objects.create(
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            action=action,
            object_repr=str(obj)[:255] if obj is not None else '',
            changes=_json_safe(changes) if changes else {},
            reason=reason,
            ip_address=ip or None,
        )
    except Exception:
        import logging
        logging.getLogger('django.security').exception('Failed to write audit log for action=%s', action)


class AutomationRun(models.Model):
    STATUS_CHOICES = [('queued','Queued'),('running','Running'),('completed','Completed'),('failed','Failed'),('partial','Partial')]
    trigger = models.CharField(max_length=50, default='manual')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AutomationTask(models.Model):
    run = models.ForeignKey(AutomationRun, on_delete=models.CASCADE, related_name='tasks')
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)


class ExceptionRecord(models.Model):
    SEVERITY_CHOICES = [('info','Info'),('warning','Warning'),('critical','Critical')]
    STATUS_CHOICES = [('open','Open'),('acknowledged','Acknowledged'),('resolved','Resolved'),('ignored','Ignored')]
    code = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    module = models.CharField(max_length=80, blank=True)
    message = models.TextField()
    object_type = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=120, blank=True)
    details = models.JSONField(default=dict, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['status','severity']), models.Index(fields=['module','code'])]


class DataQualityIssue(models.Model):
    STATUS_CHOICES = [('open','Open'),('fixed','Fixed'),('ignored','Ignored')]
    issue_type = models.CharField(max_length=80)
    model_label = models.CharField(max_length=120)
    object_id = models.CharField(max_length=120, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    details = models.JSONField(default=dict, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    fixed_at = models.DateTimeField(null=True, blank=True)


class EmailLog(models.Model):
    """One row per email the system tries to send - the honest record of
    what was really delivered to the mail server, what failed and why.
    (Django's SMTP backend reports success once the mail server accepts the
    message; this table records exactly that, nothing more.)"""
    STATUS_CHOICES = [('sent', 'Sent to mail server'), ('failed', 'Failed'), ('console', 'Printed to console (no SMTP configured)')]
    to_email = models.CharField(max_length=254)
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    category = models.CharField(max_length=50, blank=True, help_text='e.g. verification, challan, payment, grade')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='failed')
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f'{self.to_email}: {self.subject} [{self.status}]'


class EmailOTP(models.Model):
    """A short-lived 6-digit code emailed to a user. Only a keyed hash of the
    code is stored, so a database leak does not reveal usable codes. Each code
    works once, expires quickly, and locks after too many wrong guesses."""
    PURPOSES = [('verify_email', 'Verify email'), ('password_reset', 'Password reset'), ('change_email', 'Confirm new email')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_otps')
    purpose = models.CharField(max_length=20, choices=PURPOSES)
    target_email = models.EmailField(blank=True, help_text='For change_email: the new address being confirmed.')
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'purpose', '-created_at'])]


class SchedulerJob(models.Model):
    """Run-state for one recurring background job.

    One row per job name. It is the lock AND the history for the built-in
    scheduler (`manage.py run_scheduler`, the token-protected cron endpoint)
    and for Celery Beat, so the same job can never be started twice at the
    same moment no matter which trigger fires it. Acquiring the lock is a
    single atomic UPDATE (compare-and-set) that works identically on
    SQLite and PostgreSQL - no Redis, no advisory locks needed.
    """
    name = models.CharField(max_length=60, unique=True)
    last_started = models.DateTimeField(null=True, blank=True)
    last_finished = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True)   # completed | failed | skipped
    last_trigger = models.CharField(max_length=30, blank=True)  # builtin | cron | celery | manual
    last_error = models.TextField(blank=True)
    last_result = models.JSONField(default=dict, blank=True)
    run_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.last_status or "never run"})'
