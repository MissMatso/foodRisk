"""Keeping ward and village spellings consistent.

Ward and village are typed by hand, so "Hantam", "hantam " and "HANTAM" would
otherwise be counted as three different wards in every report. A new entry that
matches an existing one (ignoring case, punctuation and spacing) is stored with
the existing spelling.
"""

from django.db.models import Count

from .identity import normalise_text


def tidy(value):
    return " ".join((value or "").split())


def _spellings(field, ward=None):
    from .models import Household

    queryset = Household.objects.exclude(**{field: ""})
    if ward:
        queryset = queryset.filter(ward__iexact=ward)
    return queryset.values(field).annotate(total=Count("pk")).order_by("-total", field)


def canonical(value, field, ward=None):
    """The spelling already in use for this ward or village, else the tidied text."""
    value = tidy(value)
    if not value:
        return ""
    target = normalise_text(value)
    for row in _spellings(field, ward):
        if normalise_text(row[field]) == target:
            return row[field]
    return value


def known_wards():
    return [row["ward"] for row in _spellings("ward")]


def known_villages():
    return [row["village"] for row in _spellings("village")]
