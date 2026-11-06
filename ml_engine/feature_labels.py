"""Plain-English names for model features, used wherever an explanation is shown."""

LABELS = {
    "monthly_income": "Monthly income",
    "income_per_capita": "Income per person",
    "household_size": "Household size",
    "num_dependents": "Dependents (children under 5 + elderly)",
    "children_under_5": "Children under 5",
    "elderly_members": "Members aged 60+",
    "distance_to_market_km": "Distance to market (km)",
    "has_disabled_member": "Disabled member",
    "has_chronic_illness": "Chronic illness",
    "land_ownership": "Owns land",
    "employment_status": "Employment status",
    "water_access": "Water access",
}


def label(feature):
    return LABELS.get(feature, feature.replace("_", " ").capitalize())


def ranked(contributions):
    """[(label, value, percentage points)] sorted by size of effect, largest first."""
    return sorted(
        ((label(name), value, round(value * 100, 1)) for name, value in (contributions or {}).items()),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
