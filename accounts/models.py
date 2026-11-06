from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """Custom user model with role-based access control (FR001)."""

    ROLE_ADMIN = "admin"
    ROLE_STAFF = "staff"
    ROLE_ANALYST = "analyst"

    ROLE_CHOICES = (
        (ROLE_ADMIN, "System Admin"),
        (ROLE_STAFF, "NGO Staff"),
        (ROLE_ANALYST, "Data Analyst"),
    )

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_STAFF)
    # True while the password is one an administrator chose. The user must set their own at next sign-in.
    must_change_password = models.BooleanField(default=False)

    def is_admin_role(self):
        return self.role == self.ROLE_ADMIN

    def is_staff_role(self):
        return self.role == self.ROLE_STAFF

    def is_analyst_role(self):
        return self.role == self.ROLE_ANALYST

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class AccountEvent(models.Model):
    """Security trail for accounts: logins, failed logins, and admin actions.

    This is separate from households.AuditLog, which only tracks household
    records. For a failed login we store the typed username ONLY when it
    matches an existing account. A name that matches no account is left
    blank, because people sometimes type a password into the username box
    and that must never be written to storage.
    """

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    ROLE_CHANGED = "role_changed"
    ACCOUNT_DEACTIVATED = "account_deactivated"
    ACCOUNT_ACTIVATED = "account_activated"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    ACCOUNT_CREATED = "account_created"
    EVENT_CHOICES = [
        (LOGIN_SUCCESS, "Login"),
        (LOGIN_FAILED, "Failed login"),
        (LOGOUT, "Logout"),
        (ROLE_CHANGED, "Role changed"),
        (ACCOUNT_DEACTIVATED, "Account deactivated"),
        (ACCOUNT_ACTIVATED, "Account activated"),
        (PASSWORD_CHANGED, "Password changed"),
        (PASSWORD_RESET, "Password reset by administrator"),
        (ACCOUNT_CREATED, "Account created"),
    ]

    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, db_index=True)
    username = models.CharField(max_length=150, blank=True)
    user = models.ForeignKey(
        "accounts.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="account_events"
    )
    performed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_actions",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        who = self.username or "unknown username"
        return f"{self.get_event_type_display()} — {who} at {self.timestamp:%Y-%m-%d %H:%M}"
