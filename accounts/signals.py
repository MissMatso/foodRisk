"""Record logins, failed logins and logouts using Django's built-in signals."""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .events import record_event
from .models import AccountEvent, CustomUser


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    record_event(AccountEvent.LOGIN_SUCCESS, username=user.get_username(), user=user, request=request)


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user is not None:
        record_event(AccountEvent.LOGOUT, username=user.get_username(), user=user, request=request)


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request=None, **kwargs):
    typed_name = str(credentials.get("username", ""))[:150]
    known_user = CustomUser.objects.filter(username=typed_name).first() if typed_name else None
    if known_user is None:
        # Unknown name: keep the attempt but not the text (it may be a mistyped password).
        record_event(AccountEvent.LOGIN_FAILED, request=request, detail="Unknown username")
    else:
        record_event(
            AccountEvent.LOGIN_FAILED, username=known_user.username, user=known_user, request=request
        )
