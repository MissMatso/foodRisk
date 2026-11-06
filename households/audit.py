"""Audit trail on household create/update/delete — addresses the 'no audit
trail' gap identified in Phase 1, and matches the AuditLog entity from the
Phase 2 ERD (User, Household, Prediction, AuditLog).

Implemented as Django signals rather than overriding save() everywhere, so
it fires consistently for admin-site edits, API edits, and view edits
alike — anything that goes through Household.save() or .delete().
"""

import threading

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AuditLog, Household

# Holds the current request's user, set by AuditMiddleware, so the signal
# handlers below know *who* made a change without threading a user
# argument through every call site (Django signals don't get the request).
_local = threading.local()


class AuditMiddleware:
    """Stashes request.user on a thread-local for the signal handlers below."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.user = getattr(request, "user", None)
        try:
            return self.get_response(request)
        finally:
            _local.user = None


def _current_user():
    user = getattr(_local, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


TRACKED_FIELDS = [
    "name",
    "address",
    "contact",
    "ward",
    "village",
    "monthly_income",
    "household_size",
    "num_dependents",
    "employment_status",
    "has_disabled_member",
    "has_chronic_illness",
    "children_under_5",
    "elderly_members",
    "distance_to_market_km",
    "water_access",
    "land_ownership",
    "shared_address_reason",
]


@receiver(pre_save, sender=Household)
def stash_previous_values(sender, instance, **kwargs):
    """Runs before the row is written. For an existing row, computes a
    diff against the current DB values and stashes it on the instance so
    post_save (which has a reliable `created` flag) can use it."""
    if not instance.pk:
        instance._audit_diff = None
        return

    try:
        previous = Household.objects.get(pk=instance.pk)
    except Household.DoesNotExist:
        instance._audit_diff = None
        return

    changed_fields = []
    for field in TRACKED_FIELDS:
        old_value = getattr(previous, field)
        new_value = getattr(instance, field)
        if old_value != new_value:
            changed_fields.append(field)
    # Record what changed, never old/new values: these may contain household
    # addresses, contact numbers, income or health information.
    instance._audit_diff = {"fields_changed": changed_fields} if changed_fields else None


@receiver(post_save, sender=Household)
def log_household_save(sender, instance, created, **kwargs):
    user = _current_user()

    if created:
        AuditLog.objects.create(
            household=instance,
            household_name=instance.name,
            action=AuditLog.ACTION_CREATE,
            changed_by=user,
            changes={"created": True},
        )
        return

    diff = getattr(instance, "_audit_diff", None)
    if diff:
        AuditLog.objects.create(
            household=instance,
            household_name=instance.name,
            action=AuditLog.ACTION_UPDATE,
            changed_by=user,
            changes=diff,
        )


@receiver(post_delete, sender=Household)
def log_household_delete(sender, instance, **kwargs):
    AuditLog.objects.create(
        household=None,
        household_name=instance.name,
        action=AuditLog.ACTION_DELETE,
        changed_by=_current_user(),
        changes={"deleted": True},
    )
