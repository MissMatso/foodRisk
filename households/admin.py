from django.contrib import admin
from .models import AuditLog, Household


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "household_size", "num_dependents", "employment_status", "created_at")
    list_filter = ("employment_status",)
    # Encrypted fields cannot be searched with a database LIKE query.
    search_fields = ("name",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("household_name", "action", "changed_by", "timestamp")
    list_filter = ("action",)
    search_fields = ("household_name",)
    readonly_fields = ("household", "household_name", "action", "changed_by", "changes", "timestamp")
