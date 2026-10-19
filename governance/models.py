from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import ACTIONS, MODULES, OFFICES, SCOPE_CHOICES


class Role(models.Model):
    """A named bundle of (module, action) permissions created by the Super
    Administrator and handed out to sub-administrators."""
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, help_text='Installed by default; cannot be deleted.')
    is_active = models.BooleanField(default=True)
    office = models.CharField(max_length=20, choices=OFFICES, blank=True, default='',
                              help_text='Which university office this role belongs to (for the Governance Map).')
    rank = models.PositiveSmallIntegerField(default=100, help_text='Order inside the office (1 = most senior).')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['office', 'rank', 'name']

    def __str__(self):
        return self.name

    def permission_pairs(self):
        return set(self.permissions.values_list('module', 'action'))


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    module = models.CharField(max_length=40, choices=MODULES)
    action = models.CharField(max_length=20, choices=ACTIONS)

    class Meta:
        unique_together = [('role', 'module', 'action')]
        ordering = ['module', 'action']

    def __str__(self):
        return f'{self.role}: {self.module}.{self.action}'


class RoleAssignment(models.Model):
    """One user + one role, optionally limited to a scope and a date window."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='role_assignments')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='assignments')
    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='university')
    scope_id = models.PositiveIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True, help_text='Empty = permanent.')
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='role_grants_made')
    delegated_from = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} -> {self.role} ({self.scope_type})'

    def is_current(self, today=None):
        today = today or timezone.localdate()
        if not self.is_active or not self.role.is_active:
            return False
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        return True


class PolicyRule(models.Model):
    TYPES = [('int', 'Whole number'), ('decimal', 'Decimal'), ('bool', 'Yes / No'), ('text', 'Text')]
    key = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=40)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    value_type = models.CharField(max_length=10, choices=TYPES, default='int')

    class Meta:
        ordering = ['category', 'key']

    def __str__(self):
        return self.name

    def cast(self, raw):
        if self.value_type == 'int':
            return int(raw)
        if self.value_type == 'decimal':
            from decimal import Decimal
            return Decimal(raw)
        if self.value_type == 'bool':
            return str(raw).strip().lower() in ('1', 'true', 'yes', 'y', 'on')
        return str(raw)


class PolicyVersion(models.Model):
    rule = models.ForeignKey(PolicyRule, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    value = models.CharField(max_length=255)
    scope_type = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='university')
    scope_id = models.PositiveIntegerField(null=True, blank=True)
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('rule', 'version')]
        ordering = ['rule__key', '-version']

    def __str__(self):
        return f'{self.rule.key} v{self.version} = {self.value} ({self.scope_type})'


class EmergencyAccess(models.Model):
    """Time-limited, reasoned, audited permission for the System Administrator to
    act as an office holder when nobody holds that authority (break-glass)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='emergency_grants')
    reason = models.CharField(max_length=300)
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-granted_at']

    def is_active(self):
        from django.utils import timezone
        return self.revoked_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f'{self.user} until {self.expires_at:%d %b %H:%M}'
