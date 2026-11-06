"""Shared feature contract for GHS 2024 training and live assessments."""

import math

SCHEMA_VERSION = "ghs2024-food-access-v1"
NUMERIC_FEATURES = [
    "monthly_income",
    "income_per_capita",
    "household_size",
    "children_under_5",
    "elderly_members",
]
CATEGORICAL_FEATURES = ["province", "water_access"]
FEATURE_COLS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "reported_food_shortage"
TARGET_DEFINITION = (
    "GHS 2024 FSD8: household ran out of food because of insufficient "
    "money/resources during the last 12 months (1=Yes, 2=No)."
)
INCOME_CAP = 20000.0
PROVINCES = [
    (str(i), n)
    for i, n in enumerate(
        [
            "Western Cape",
            "Eastern Cape",
            "Northern Cape",
            "Free State",
            "KwaZulu-Natal",
            "North West",
            "Gauteng",
            "Mpumalanga",
            "Limpopo",
        ],
        1,
    )
]
WATER_MAP = {
    1: "piped",
    2: "piped",
    3: "borehole",
    5: "communal",
    6: "communal",
    9: "borehole",
    10: "river",
    11: "river",
}
WATER_VALUES = {"piped", "borehole", "communal", "river", "other"}


def from_household(household):
    size = getattr(household, "household_size", None)
    if size is None:
        raise KeyError("household_size")
    if size <= 0:
        raise ValueError("Invalid household size")
    income = getattr(household, "monthly_income", None)
    if income is not None:
        income = float(income)
        if not math.isfinite(income) or income < 0:
            raise ValueError("Invalid income")
        income = min(income, INCOME_CAP)
    result = {
        "monthly_income": income,
        "income_per_capita": income / size if income is not None else None,
        "household_size": size,
        "children_under_5": household.children_under_5,
        "elderly_members": household.elderly_members,
        "province": str(household.province),
        "water_access": household.water_access,
    }
    if result["province"] not in dict(PROVINCES):
        raise KeyError("province")
    # The old 'none' category has no matched GHS category. It is treated as
    # unknown, never silently recoded to a particular water source.
    if result["water_access"] not in WATER_VALUES:
        result["water_access"] = None
    return result
