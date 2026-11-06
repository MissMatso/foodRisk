"""Train a versioned demonstration candidate using the unchanged original CSV."""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .simulated_features import (
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES,
    FEATURE_COLS,
    SCHEMA_VERSION,
    TARGET,
    TARGET_DEFINITION,
)
from .registry import digest, version_directory
from .monitoring import reference_profile
from .train_model import metrics, REQUIRED_METRICS

DATA_PATH = Path(__file__).parent / "data" / "nc-food-insecurity-training.csv"


def load_dataframe():
    df = pd.read_csv(DATA_PATH)
    if not df.household_id.is_unique or not set(df.risk_label).issubset({"low", "medium", "high"}):
        raise ValueError("Invalid simulated dataset identifiers or labels")
    if not df.household_size.gt(0).all():
        raise ValueError("Invalid household size")
    df["income_per_capita"] = df.monthly_income / df.household_size
    df["num_dependents"] = df.children_under_5 + df.elderly_members
    df[TARGET] = df.risk_label.eq("high").astype(int)
    return df


def split_data(df):
    remaining, test = train_test_split(df, test_size=0.2, random_state=42, stratify=df[TARGET])
    train, validation = train_test_split(
        remaining, test_size=0.25, random_state=43, stratify=remaining[TARGET]
    )
    return {"train": train, "validation": validation, "test": test}


def build_preprocessor():
    return ColumnTransformer(
        [
            (
                "num",
                Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]),
                NUMERIC_FEATURES,
            ),
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                CATEGORICAL_FEATURES,
            ),
        ]
    )


def main(version=None):
    version = version or datetime.now(timezone.utc).strftime("simulated_rf_%Y%m%dT%H%M%S%fZ")
    destination = version_directory(version)
    destination.mkdir(parents=True, exist_ok=False)
    df = load_dataframe()
    splits = split_data(df)
    train, validation, test = (splits[k] for k in ("train", "validation", "test"))
    classifiers = {
        "dummy": DummyClassifier(strategy="prior"),
        "logistic_regression": LogisticRegression(max_iter=2000, random_state=42),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=12,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=42,
            n_jobs=1,
        ),
    }
    results = {}
    for name, classifier in classifiers.items():
        model = Pipeline([("preprocessor", build_preprocessor()), ("classifier", classifier)])
        model.fit(train[FEATURE_COLS], train[TARGET])
        scores = model.predict_proba(test[FEATURE_COLS])[:, 1]
        results[name] = {
            "validation": metrics(
                validation[TARGET], model.predict_proba(validation[FEATURE_COLS])[:, 1], 0.5
            ),
            "test": metrics(test[TARGET], scores, 0.5),
        }
        if name == "random_forest":
            primary, primary_scores = model, scores
    joblib.dump(primary, destination / "model.joblib", compress=3)
    membership = df[["household_id"]].copy()
    for name, split in splits.items():
        membership.loc[split.index, "split"] = name
    membership.to_csv(destination / "split_membership.csv", index=False)
    review = test[["household_id", TARGET]].copy()
    review["probability"] = primary_scores
    review["predicted_label"] = (primary_scores >= 0.5).astype(int)
    review["review_group"] = np.select(
        [
            (review[TARGET] == 0) & (review.predicted_label == 1),
            (review[TARGET] == 1) & (review.predicted_label == 0),
        ],
        ["false_positive", "false_negative"],
        default="correct",
    )
    review.to_csv(destination / "test_predictions.csv", index=False)
    passed = all(results["random_forest"]["test"][k] >= v for k, v in REQUIRED_METRICS.items())
    audit = {
        "dataset_type": "simulated",
        "source": "Original user-supplied foodrisk_project (1)(1).zip",
        "file": "ml_engine/data/nc-food-insecurity-training.csv",
        "sha256": digest(DATA_PATH),
        "rows": len(df),
        "raw_missing_values": int(pd.read_csv(DATA_PATH).isna().sum().sum()),
        "label_counts": df.risk_label.value_counts().to_dict(),
        "notice": (
            "Original CSV bytes restored unchanged. Generated labels and complete data; "
            "not real NGO records. No artificial missingness added."
        ),
    }
    root = Path(__file__).parent
    manifest = {
        "model_version": version,
        "status": "research_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_schema": SCHEMA_VERSION,
        "features": FEATURE_COLS,
        "target": TARGET_DEFINITION,
        "artifact_sha256": digest(destination / "model.joblib"),
        "data_lineage": audit,
        "code_sha256": {
            n: digest(root / n)
            for n in ("train_simulated.py", "simulated_features.py", "train_model.py", "monitoring.py")
        },
        "requirements_sha256": digest(root.parent / "requirements.txt"),
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__},
        "algorithm": "RandomForestClassifier",
        "parameters": classifiers["random_forest"].get_params(),
        "selection": (
            "Predeclared Random Forest architecture; fixed binary threshold 0.5; "
            "no test-set selection or tuning."
        ),
        "split": {n: {"rows": len(s), "positives": int(s[TARGET].sum())} for n, s in splits.items()},
        "split_policy": (
            "Stratified 60/20/20 row split; test seed42, validation seed43. "
            "Fit preprocessing on train only. No real-world generalisation claim."
        ),
        "decision_threshold": 0.5,
        "comparisons": results,
        "high_display_band_test": metrics(test[TARGET], primary_scores, 0.66005),
        "display_bands": (
            "Rounded score <=33 Low, <=66 Medium, otherwise High; "
            "display bands are not the evaluation threshold."
        ),
        "validation": {
            "rubric_targets": REQUIRED_METRICS,
            "rubric_targets_met": passed,
            "ngo_external_validation": False,
            "limitations": (
                "Simulated labels only; measured scores do not validate real household risk. "
                "No real-data, NGO, future-outcome or probability-calibration validation. "
                "The lecturer's real-data requirement remains unmet."
            ),
        },
        "drift_reference": reference_profile(train[FEATURE_COLS], NUMERIC_FEATURES, CATEGORICAL_FEATURES),
    }
    for filename, content in [("manifest.json", manifest), ("data_audit.json", audit)]:
        (destination / filename).write_text(json.dumps(content, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(
        f"Saved simulated-data candidate: {version}. Synthetic test targets met: {passed}; "
        "real-data requirement remains unmet."
    )
    return passed
