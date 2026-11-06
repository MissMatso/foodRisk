"""Model performance card for the Analyst report.

Nothing is recomputed here. The results were recorded in the model's
manifest when it was trained, so the card always describes the model that
is actually serving predictions (settings.FOODRISK_MODEL_VERSION), on the
dataset it was trained on. It never mixes datasets.
"""

import json

from django.conf import settings

from ml_engine.registry import version_directory

BASELINE_NAMES = [
    ("dummy", "Always predicts the majority class"),
    ("logistic_regression", "Logistic regression"),
    ("random_forest", "Random forest (the model used)"),
]


def _percent(value):
    return round(value * 100, 1)


def build_model_card(version=None):
    """Returns a dict for the template, or None if the manifest is unusable."""
    version = version or settings.FOODRISK_MODEL_VERSION
    try:
        manifest = json.loads((version_directory(version) / "manifest.json").read_text(encoding="utf-8"))
        forest = manifest["comparisons"]["random_forest"]["test"]
        tn, fp, fn, tp = forest["confusion_matrix_tn_fp_fn_tp"]
    except (OSError, ValueError, KeyError, TypeError):
        return None

    targets = manifest.get("validation", {}).get("rubric_targets", {})
    accuracy = (tn + tp) / forest["n"]
    values = [
        ("Accuracy", "accuracy", accuracy),
        ("Precision", "precision", forest["precision"]),
        ("Recall", "recall", forest["recall"]),
        ("F1 score", "f1", forest["f1"]),
        ("ROC AUC", "roc_auc", forest["roc_auc"]),
    ]
    tiles = []
    for label, key, value in values:
        target = targets.get(key)  # accuracy has no required minimum
        tiles.append(
            {
                "label": label,
                "percent": _percent(value),
                "target_percent": round(target * 100) if target else None,
                "meets_target": (value >= target) if target else None,
            }
        )

    baselines = []
    for key, label in BASELINE_NAMES:
        result = manifest["comparisons"].get(key, {}).get("test")
        if result:
            baselines.append(
                {"label": label, "f1": _percent(result["f1"]), "roc_auc": _percent(result["roc_auc"])}
            )

    band = manifest.get("high_display_band_test") or {}
    lineage = manifest.get("data_lineage", {})
    return {
        "version": version,
        "status": manifest.get("status", ""),
        "dataset": lineage.get("dataset_type") or manifest.get("feature_schema", ""),
        "test_rows": forest["n"],
        "tiles": tiles,
        "matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "baselines": baselines,
        "band_threshold": band.get("threshold"),
        "band_precision": _percent(band["precision"]) if band else None,
        "band_recall": _percent(band["recall"]) if band else None,
        "targets_met": manifest.get("validation", {}).get("rubric_targets_met"),
        "externally_validated": bool(manifest.get("validation", {}).get("ngo_external_validation")),
        "limitations": manifest.get("validation", {}).get("limitations", ""),
    }
