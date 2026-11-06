"""Small helper for writing AccountEvent rows."""

from .models import AccountEvent


def client_ip(request):
    """The connecting address. We deliberately do not trust X-Forwarded-For,
    because anyone can fake that header."""
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def record_event(event_type, username="", user=None, performed_by=None, request=None, detail=""):
    return AccountEvent.objects.create(
        event_type=event_type,
        username=(username or "")[:150],
        user=user,
        performed_by=performed_by,
        ip_address=client_ip(request),
        detail=detail[:200],
    )
