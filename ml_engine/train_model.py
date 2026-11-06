"""Train an immutable research candidate on real GHS 2024 public-use data."""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .features import (
    CATEGORICAL_FEATURES,
    FEATURE_COLS,
    NUMERIC_FEATURES,
    SCHEMA_VERSION,
    TARGET,
    TARGET_DEFINITION,
)
from .ghs_data import load_ghs, sha256
from .monitoring import reference_profile
from .registry import version_directory

REQUIRED_METRICS = {"f1": 0.85, "precision": 0.80, "recall": 0.85, "roc_auc": 0.90}


def load_dataframe():
    return load_ghs()[0]


def build_preprocessor():
    return ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
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


def split_data(df):
    # Split survey sampling clusters, not individual rows, to reduce leakage.
    train_val, test = next(
        GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(df, groups=df.psu)
    )
    remaining = df.iloc[train_val]
    train, validation = next(
        GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=43).split(remaining, groups=remaining.psu)
    )
    return {"train": remaining.iloc[train], "validation": remaining.iloc[validation], "test": df.iloc[test]}


def metrics(y, scores, threshold, weights=None):
    labels = np.asarray(scores) >= threshold
    result = {"n": len(y), "positive_n": int(np.asarray(y).sum()), "threshold": float(threshold)}
    for key, func in [("f1", f1_score), ("precision", precision_score), ("recall", recall_score)]:
        result[key] = float(func(y, labels, sample_weight=weights, zero_division=0))
    result["roc_auc"] = float(roc_auc_score(y, scores, sample_weight=weights)) if len(set(y)) > 1 else None
    result["average_precision"] = (
        float(average_precision_score(y, scores, sample_weight=weights)) if len(set(y)) > 1 else None
    )
    result["brier"] = float(brier_score_loss(y, scores, sample_weight=weights))
    result["confusion_matrix_tn_fp_fn_tp"] = (
        confusion_matrix(y, labels, labels=[0, 1], sample_weight=weights).ravel().tolist()
    )
    return result


def main(version=None):
    version = version or datetime.now(timezone.utc).strftime("ghs2024_rf_%Y%m%dT%H%M%S%fZ")
    destination = version_directory(version)
    # Reserve a new version before training: never overwrite an existing release.
    destination.mkdir(parents=True, exist_ok=False)
    df, audit = load_ghs()
    splits = split_data(df)
    train, validation, test = (splits[k] for k in ("train", "validation", "test"))
    classifiers = {
        "dummy": DummyClassifier(strategy="prior"),
        "logistic_regression": LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=1,
        ),
    }
    results = {}
    for name, classifier in classifiers.items():
        pipeline = Pipeline([("preprocessor", build_preprocessor()), ("classifier", classifier)])
        pipeline.fit(train[FEATURE_COLS], train[TARGET])
        val_scores = pipeline.predict_proba(validation[FEATURE_COLS])[:, 1]
        thresholds = np.arange(0.10, 0.91, 0.01)
        threshold = float(
            thresholds[
                np.argmax(
                    [f1_score(validation[TARGET], val_scores >= t, zero_division=0) for t in thresholds]
                )
            ]
        )
        scores = pipeline.predict_proba(test[FEATURE_COLS])[:, 1]
        results[name] = {
            "validation": metrics(validation[TARGET], val_scores, threshold),
            "test": metrics(test[TARGET], scores, threshold),
        }
        if name == "random_forest":
            primary, primary_scores, primary_threshold = pipeline, scores, threshold
    joblib.dump(primary, destination / "model.joblib", compress=3)
    membership = df[["survey_id", "psu"]].copy()
    for name, split in splits.items():
        membership.loc[split.index, "split"] = name
    membership.to_csv(destination / "split_membership.csv", index=False)
    review = test[["survey_id", "psu", "province", TARGET]].copy()
    review["probability"] = primary_scores
    review["predicted_label"] = (primary_scores >= primary_threshold).astype(int)
    review["review_group"] = np.select(
        [
            (review[TARGET] == 0) & (review.predicted_label == 1),
            (review[TARGET] == 1) & (review.predicted_label == 0),
        ],
        ["false_positive", "false_negative"],
        default="correct",
    )
    review.to_csv(destination / "test_predictions.csv", index=False)
    nc = test.province.eq("3")
    passed = all(results["random_forest"]["test"][k] >= v for k, v in REQUIRED_METRICS.items())
    root = Path(__file__).parent
    manifest = {
        "model_version": version,
        "status": "research_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_schema": SCHEMA_VERSION,
        "features": FEATURE_COLS,
        "target": TARGET_DEFINITION,
        "artifact_sha256": sha256(destination / "model.joblib"),
        "data_lineage": audit,
        "code_sha256": {n: sha256(root / n) for n in ("train_model.py", "features.py", "ghs_data.py")},
        "requirements_sha256": sha256(root.parent / "requirements.txt"),
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__},
        "algorithm": "RandomForestClassifier",
        "parameters": classifiers["random_forest"].get_params(),
        "selection": (
            "Random Forest predeclared for the existing TreeSHAP architecture; "
            "baselines reported without selecting on test results."
        ),
        "split": {
            n: {"rows": len(s), "psus": int(s.psu.nunique()), "positives": int(s[TARGET].sum())}
            for n, s in splits.items()
        },
        "split_policy": (
            "GroupShuffleSplit by PSU; 20% test seed42; 25% of remaining validation "
            "seed43. All preprocessing fit on train only. Threshold maximises "
            "validation F1; no test tuning."
        ),
        "decision_threshold": primary_threshold,
        "comparisons": results,
        "weighted_test_sensitivity": metrics(
            test[TARGET], primary_scores, primary_threshold, test.survey_weight
        ),
        "northern_cape_test": metrics(test.loc[nc, TARGET], primary_scores[nc], primary_threshold),
        "high_display_band_test": metrics(test[TARGET], primary_scores, 0.66005),
        "display_bands": (
            "Rounded score <=33 Low, <=66 Medium, otherwise High. Indicative UI bands; "
            "not the binary evaluation threshold or validated severity levels."
        ),
        "validation": {
            "rubric_targets": REQUIRED_METRICS,
            "rubric_targets_met": passed,
            "ngo_external_validation": False,
            "limitations": (
                "Cross-sectional national survey, modest proxy features, uncalibrated "
                "class-balanced scores. No future-event, NGO, temporal or causal "
                "validation. Weights are a sensitivity analysis, not a design-based "
                "population estimate."
            ),
        },
        "drift_reference": reference_profile(train[FEATURE_COLS]),
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (destination / "data_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    for name, result in results.items():
        print(name, json.dumps(result["test"]))
    print(f"Saved candidate: {version}. Rubric targets met: {passed}. Activation is separate.")
    return passed


if __name__ == "__main__":
    main()
