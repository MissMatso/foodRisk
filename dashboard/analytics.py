"""Group-level analytics for the Data Analyst: how risk is spread across wards and employment groups.

Each household counts once, using its latest assessment from the model that is
currently serving, so a household scored three times does not count three times.
"""

from django.conf import settings
from django.db.models import Avg, Count, Q

from .exports import latest_per_household

GROUPS = {
    "ward": ("household__ward", "Ward"),
    "village": ("household__village", "Village"),
    "employment": ("household__employment_status", "Employment status"),
}


def breakdown(predictions, group):
    """Rows of {label, households, average, low, medium, high, high_share} for one grouping."""
    field, _title = GROUPS[group]
    labels = {}
    if group == "employment":
        from households.models import Household

        labels = dict(Household.EMPLOYMENT_CHOICES)
    rows = (
        latest_per_household(predictions)
        .values(field)
        .annotate(
            households=Count("household", distinct=True),
            average=Avg("score"),
            low=Count("pk", filter=Q(category="Low")),
            medium=Count("pk", filter=Q(category="Medium")),
            high=Count("pk", filter=Q(category="High")),
        )
        .order_by("-high", field)
    )
    result = []
    for row in rows:
        total = row["households"] or 1
        result.append(
            {
                "label": labels.get(row[field], row[field]) or "(not recorded)",
                "households": row["households"],
                "average": round(row["average"] or 0, 1),
                "low": row["low"],
                "medium": row["medium"],
                "high": row["high"],
                "high_share": round(100 * row["high"] / total, 1),
            }
        )
    return result


def all_breakdowns(predictions):
    return {
        "model_version": settings.FOODRISK_MODEL_VERSION,
        "ward": breakdown(predictions, "ward"),
        "employment": breakdown(predictions, "employment"),
    }


def response_coverage(predictions):
    """Are high-risk households being reached? Counts for the filtered, current-model assessments.

    Each household counts once, using its latest current-model assessment. A household
    counts as reached when any intervention has been recorded against any of its
    assessments, so rescoring a household does not make an earlier action disappear.
    Only counts are returned: no names, addresses or phone numbers.
    """
    from django.utils import timezone

    from predictions.models import Intervention

    latest = list(latest_per_household(predictions).values("household_id", "category", "household__ward"))
    household_ids = [row["household_id"] for row in latest]
    actions = Intervention.objects.filter(prediction__household_id__in=household_ids)
    reached = set(actions.values_list("prediction__household_id", flat=True))
    today = timezone.localdate()
    open_actions = actions.filter(status="open")
    overdue_ids = set(
        open_actions.filter(follow_up_date__lt=today).values_list("prediction__household_id", flat=True)
    )
    open_ids = set(open_actions.values_list("prediction__household_id", flat=True))

    wards = {}
    for row in latest:
        ward = wards.setdefault(
            row["household__ward"] or "(not recorded)",
            {"high": 0, "high_reached": 0, "open": 0, "overdue": 0},
        )
        if row["category"] == "High":
            ward["high"] += 1
            ward["high_reached"] += row["household_id"] in reached
        ward["open"] += row["household_id"] in open_ids
        ward["overdue"] += row["household_id"] in overdue_ids
    rows = []
    for name, w in wards.items():
        not_reached = w["high"] - w["high_reached"]
        share = round(100 * w["high_reached"] / w["high"], 1) if w["high"] else None
        rows.append({"ward": name, **w, "not_reached": not_reached, "reached_share": share})
    rows.sort(key=lambda r: (-r["not_reached"], r["ward"]))

    high = sum(r["high"] for r in rows)
    high_reached = sum(r["high_reached"] for r in rows)
    return {
        "high": high,
        "high_reached": high_reached,
        "not_reached": high - high_reached,
        "reached_share": round(100 * high_reached / high, 1) if high else None,
        "open": len(open_ids),
        "overdue": len(overdue_ids),
        "by_ward": rows,
    }
