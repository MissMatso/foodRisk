"""Role-based access control mixins (FR001, NFR006).

These enforce RBAC on top of LoginRequiredMixin using Django's
UserPassesTestMixin, as required by the spec.
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Base mixin: subclass and set `allowed_roles`."""

    allowed_roles = ()
    raise_exception = False

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.role in self.allowed_roles

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("You do not have permission to access this page.")


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin",)


class StaffRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin", "staff")


class AnalystRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin", "analyst")


class StaffOrAnalystRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("admin", "staff", "analyst")
