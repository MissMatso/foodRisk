"""Keep users who still have an administrator-issued password on the change-password page."""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """A user whose password was set by an administrator must choose their own before doing anything else.

    Allowed meanwhile: the change-password pages, signing out, and static files.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not self.is_allowed(request)
        ):
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "You must choose your own password before using the system."}, status=403
                )
            return redirect("accounts:password_change")
        return self.get_response(request)

    @staticmethod
    def is_allowed(request):
        allowed = {
            reverse("accounts:password_change"),
            reverse("accounts:password_change_done"),
            reverse("accounts:logout"),
        }
        return request.path in allowed or request.path.startswith(settings.STATIC_URL)
