from django.contrib import admin

from .models import PolicyRule, PolicyVersion, Role, RoleAssignment, RolePermission


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_system', 'is_active')
    inlines = [RolePermissionInline]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'scope_type', 'scope_id', 'end_date', 'is_active')
    list_filter = ('role', 'is_active', 'scope_type')


admin.site.register(PolicyRule)


@admin.register(PolicyVersion)
class PolicyVersionAdmin(admin.ModelAdmin):
    list_display = ('rule', 'version', 'value', 'scope_type', 'effective_from', 'effective_until')

    def has_delete_permission(self, request, obj=None):
        return False  # policy history is never deleted
