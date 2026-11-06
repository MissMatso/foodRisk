"""Feature contract for the original simulated demonstration dataset."""

import math

SCHEMA_VERSION = "simulated-household-v1"
NUMERIC_FEATURES = [
    "monthly_income",
    "income_per_capita",
    "household_size",
    "num_dependents",
    "children_under_5",
    "elderly_members",
    "distance_to_market_km",
    "has_disabled_member",
    "has_chronic_illness",
    "land_ownership",
]
CATEGORICAL_FEATURES = ["employment_status", "water_access"]
FEATURE_COLS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "simulated_high_risk"
TARGET_DEFINITION = (
    "Original simulated risk_label: high=1; low or medium=0. Not an observed food-security outcome."
)


def from_household(household):
    result = {}
    for name in NUMERIC_FEATURES:
        if name in {"income_per_capita", "num_dependents", "monthly_income"}:
            continue
        value = getattr(household, name, None)
        if value is None:
            raise KeyError(name)
        result[name] = int(value)
    size = result["household_size"]
    if size <= 0:
        raise ValueError("Invalid household size")
    income = getattr(household, "monthly_income", None)
    if income is not None:
        income = float(income)
        if not math.isfinite(income) or income < 0:
            raise ValueError("Invalid income")
    result["monthly_income"] = income
    result["income_per_capita"] = income / size if income is not None else None
    # Match the original CSV derivation, not the broader case-management count.
    result["num_dependents"] = result["children_under_5"] + result["elderly_members"]
    for name in CATEGORICAL_FEATURES:
        value = getattr(household, name, None)
        if value is None:
            raise KeyError(name)
        result[name] = value
    # The old CSV contains 'none', but not the later 'other' water choice.
    if result["water_access"] == "other":
        result["water_access"] = None
    return result
