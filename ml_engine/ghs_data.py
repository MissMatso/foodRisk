"""Reproducible, codebook-based conversion of the supplied public-use files."""

import hashlib
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .features import FEATURE_COLS, INCOME_CAP, TARGET, TARGET_DEFINITION, WATER_MAP

DATA_DIR = Path(__file__).parent / "data" / "ghs2024"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_ghs(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    house_path = data_dir / "ghs-2024-hhold-v1.dta"
    person_path = data_dir / "ghs-2024-person-v1.dta"
    # Stata labels contain a few Latin-1 strings; selected analysis values
    # are numeric codes and are explicitly decoded below.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnicodeWarning)
        hh = pd.read_stata(house_path, convert_categoricals=False)
        people = pd.read_stata(person_path, convert_categoricals=False)
    if hh.uqnr.duplicated().any() or people.duplicated(["uqnr", "personnr"]).any():
        raise ValueError("Duplicate survey household/person keys; investigate before training")
    age = people.age.where(people.age.between(0, 120))
    counts = pd.DataFrame(
        {
            "uqnr": people.uqnr,
            "under5": (age < 5).astype(int),
            "over60": (age >= 60).astype(int),
            "unknown_age": age.isna().astype(int),
        }
    )
    counts = counts.groupby("uqnr").sum()
    sizes = people.groupby("uqnr").size()
    if set(sizes.index) != set(hh.uqnr) or not hh.hholdsz.eq(hh.uqnr.map(sizes)).all():
        raise ValueError("Household roster counts do not match household sizes")
    df = pd.DataFrame(index=hh.index)
    income = hh.totmhinc.where(hh.totmhinc.ne(9999999) & hh.totmhinc.ge(0))
    df["monthly_income"] = income.clip(upper=INCOME_CAP)
    df["household_size"] = hh.hholdsz
    df["income_per_capita"] = df.monthly_income / df.household_size
    known_age = hh.uqnr.map(counts.unknown_age).eq(0)
    df["children_under_5"] = hh.uqnr.map(counts.under5).where(known_age)
    df["elderly_members"] = hh.uqnr.map(counts.over60).where(known_age)
    df["province"] = hh.prov.astype(str)
    df["water_access"] = hh.wat_drinkwat.map(lambda n: WATER_MAP.get(n, "other") if 1 <= n <= 16 else np.nan)
    df[TARGET] = hh.fsd_ranout.map({1: 1, 2: 0})
    df["survey_id"] = hh.uqnr.astype("int64").astype(str)
    df["psu"] = hh.psu.astype("int64").astype(str)
    df["survey_weight"] = hh.house_wgt
    audit = {
        "source": "Statistics South Africa, General Household Survey 2024 v1; DataFirst, CC-BY",
        "source_url": "https://www.datafirst.uct.ac.za/dataportal/index.php/catalog/1027",
        "doi": "10.25828/rx6h-3r34",
        "data_kind": "real_survey",
        "raw_sha256": {p.name: sha256(p) for p in (house_path, person_path)},
        "households": len(hh),
        "people": len(people),
        "northern_cape_households": int(hh.prov.eq(3).sum()),
        "duplicate_household_ids": 0,
        "roster_counts_verified": True,
        "raw_income_unspecified": int(hh.totmhinc.eq(9999999).sum()),
        "raw_target_unspecified": int(df[TARGET].isna().sum()),
        "income_above_cap": int(income.gt(INCOME_CAP).sum()),
        "income_cap": INCOME_CAP,
        "income_note": (
            "Codebook p106 describes restricted measurement above R20000 although "
            "released values exceed it. Preserve raw data and cap model income at "
            "R20000 consistently at training/inference; no outlier rows removed."
        ),
        "target_definition": TARGET_DEFINITION,
        "missing_before_imputation": {c: int(df[c].isna().sum()) for c in FEATURE_COLS},
        "excluded_target_rows": int(df[TARGET].isna().sum()),
        "retained_rows": int(df[TARGET].notna().sum()),
        "target_counts": {str(int(k)): int(v) for k, v in df[TARGET].value_counts().items()},
        "scope": (
            "National cross-sectional survey. Target is reported past food shortage, "
            "not future hunger or a validated food-insecurity severity scale. NGO "
            "validation is outstanding."
        ),
    }
    return df.loc[df[TARGET].notna()].copy(), audit
