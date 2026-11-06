from django.contrib.auth import logout as auth_logout
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView
from django.views import View
from django.shortcuts import get_object_or_404

from .events import record_event
from .passwords import generate_temporary_password
from .roles import workspace_url
from .forms import CustomUserCreationForm, FoodRiskAuthenticationForm, StyledPasswordChangeForm
from .mixins import AdminRequiredMixin
from .models import AccountEvent, CustomUser


class PasswordChangeFlowView(PasswordChangeView):
    """Any signed-in user changes their own password (the standard password rules apply)."""

    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)  # also keeps the user signed in
        user = self.request.user
        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
        record_event(
            AccountEvent.PASSWORD_CHANGED,
            username=self.request.user.username,
            user=self.request.user,
            performed_by=self.request.user,
            request=self.request,
        )
        return response


class PasswordChangeFinishedView(PasswordChangeDoneView):
    template_name = "accounts/password_change_done.html"


class CustomLoginView(LoginView):
    """Authenticate User (all roles) — FR001.

    A browser shares one session across its tabs. If someone opens the sign-in
    page while already signed in, the page says who is signed in and offers
    "Sign out" instead of silently sending them into that account's pages.
    """

    template_name = "accounts/login.html"
    authentication_form = FoodRiskAuthenticationForm
    redirect_authenticated_user = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context["signed_in_as"] = self.request.user
            context["workspace"] = workspace_url(self.request.user)
        return context

    def get_default_redirect_url(self):
        # Used when there is no safe ?next= address. System admins land on the system report.
        return workspace_url(self.request.user)


def csrf_failure(request, reason=""):
    """Shown instead of Django's technical 403 page when a form's security token has expired.

    The usual cause is signing in or out in another tab of the same browser, which
    replaces the token that an already-open form still carries.
    """
    response = render(request, "403_csrf.html", {"sign_in": reverse_lazy("accounts:login")})
    response.status_code = 403
    return response


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("accounts:login")


@method_decorator(never_cache, name="dispatch")
class UserRegisterView(AdminRequiredMixin, CreateView):
    """Register User Account — System Admin only.

    The administrator enters the username, name, e-mail and role. The system
    generates a temporary password and shows it ONCE on the next page, so the
    administrator can hand the username and password to the new user in person.
    At first sign-in the user must choose their own password.
    """

    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = "accounts/register.html"

    def form_valid(self, form):
        user = form.save()
        record_event(
            AccountEvent.ACCOUNT_CREATED,
            username=user.username,
            user=user,
            performed_by=self.request.user,
            request=self.request,
            detail=f"role {user.role}",
        )
        # Shown on this page only, never stored in messages, logs or the event record.
        return render(
            self.request,
            "accounts/password_reset_result.html",
            {"target": user, "temporary_password": form.temporary_password, "new_account": True},
        )


class UserListView(AdminRequiredMixin, ListView):
    """Manage User Access — System Admin only.

    The one place where accounts are managed: create, change role, reset the
    password, deactivate or reactivate. Deactivating blocks sign-in but keeps the
    account and everything it recorded, so it can be reactivated later.
    """

    model = CustomUser
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    ordering = ["username"]

    def get_queryset(self):
        users = super().get_queryset()
        role, status, query = (self.request.GET.get(k, "") for k in ("role", "status", "q"))
        if role in dict(CustomUser.ROLE_CHOICES):
            users = users.filter(role=role)
        if status in ("active", "inactive"):
            users = users.filter(is_active=status == "active")
        if query.strip():
            users = users.filter(username__icontains=query.strip())
        return users

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for account in context["users"]:
            account.can_manage = not _cannot_change(self.request, account)
        context["role_choices"] = CustomUser.ROLE_CHOICES
        context["selected"] = {k: self.request.GET.get(k, "") for k in ("role", "status", "q")}
        return context


def _back_to(request, default):
    """Go back to the page the form was on (the `next` field), but only if it
    is a page on THIS site. Anything else falls back to `default`."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(default)


def _cannot_change(request, target):
    """Admins may not edit their own account, and only a superuser may edit a superuser."""
    return target.pk == request.user.pk or (target.is_superuser and not request.user.is_superuser)


class UserStatusView(AdminRequiredMixin, View):
    """Activate or deactivate an account (user list and system report)."""

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk)
        if _cannot_change(request, target):
            messages.error(request, "This account cannot be changed here.")
        elif request.POST.get("active") in ("0", "1"):
            target.is_active = request.POST["active"] == "1"
            target.save(update_fields=["is_active"])
            record_event(
                AccountEvent.ACCOUNT_ACTIVATED if target.is_active else AccountEvent.ACCOUNT_DEACTIVATED,
                username=target.username,
                user=target,
                performed_by=request.user,
                request=request,
            )
            if target.is_active:
                messages.success(request, f"{target.username} is reactivated and can sign in again.")
            else:
                messages.success(
                    request,
                    f"{target.username} is deactivated: signed out and blocked from signing in. "
                    "The account and its records are kept; reactivate it at any time.",
                )
        else:
            messages.error(request, "Invalid account status.")
        return _back_to(request, "accounts:user_list")


@method_decorator(never_cache, name="dispatch")
class UserPasswordResetView(AdminRequiredMixin, View):
    """Give an account a new temporary password (shown once) that its owner must replace."""

    http_method_names = ["post"]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk)
        if _cannot_change(request, target):
            messages.error(request, "This account cannot be changed here.")
            return redirect("accounts:user_list")
        temporary_password = generate_temporary_password()
        target.set_password(temporary_password)  # also signs the user out everywhere
        target.must_change_password = True
        target.save(update_fields=["password", "must_change_password"])
        record_event(
            AccountEvent.PASSWORD_RESET,
            username=target.username,
            user=target,
            performed_by=request.user,
            request=request,
        )
        # Shown on this page only, never stored in messages, logs or the event record.
        return render(
            request,
            "accounts/password_reset_result.html",
            {"target": target, "temporary_password": temporary_password},
        )


class UserRoleView(AdminRequiredMixin, View):
    """Change an account's application role (System Admin only)."""

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk)
        new_role = request.POST.get("role", "")
        valid_roles = [code for code, _label in CustomUser.ROLE_CHOICES]

        if _cannot_change(request, target):
            messages.error(request, "This account cannot be changed here.")
        elif new_role not in valid_roles:
            messages.error(request, "Invalid role.")
        elif new_role == target.role:
            messages.info(request, "Role was not changed.")
        else:
            old_role = target.role
            target.role = new_role
            target.save(update_fields=["role"])
            record_event(
                AccountEvent.ROLE_CHANGED,
                username=target.username,
                user=target,
                performed_by=request.user,
                request=request,
                detail=f"{old_role} -> {new_role}",
            )
            messages.success(request, f"{target.username} is now {target.get_role_display()}.")
        return _back_to(request, "accounts:user_list")
