"""One place that decides what a System Admin sees first.

A System Admin oversees accounts, sign-in security and system health. They
do not handle individual household cases, so their menu and landing page are
the system report. Permissions are unchanged: this only controls what is
shown, and every page still checks the role itself (accounts/mixins.py).
"""

from django.urls import reverse


def is_system_admin(user):
    return bool(user.is_authenticated and (user.is_superuser or user.role == "admin"))


def sees_personal_details(user):
    """Address and phone number are for the people who work with households, not for analysts."""
    return is_system_admin(user) or user.role == "staff"


def workspace_url(user):
    """The page that is 'home' for this user once signed in."""
    if is_system_admin(user):
        return reverse("dashboard:admin_report")
    return reverse("dashboard:risk_dashboard")


def navigation(request):
    """Template context processor: lets every template ask the same question."""
    return {"is_system_admin": is_system_admin(request.user), "workspace_url": workspace_url(request.user)}
