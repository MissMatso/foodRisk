"""Model-wide SHAP summary: which features move the score most, measured on held-out test records.

A single SHAP explanation says why ONE household got its score. This module
answers the model-wide question ("which features matter most overall?") the
standard way: explain every record in the model's held-out test set and take
the mean of the absolute SHAP values per feature.

The result is written next to the model as ``global_explanation.json`` and is
read by the analyst report and the prediction page. It is computed once per
model version (``python manage.py explain_model``), not on every page view.

What it is and is not:
  * baseline: the model's average score on its training data. Every individual
    explanation starts here; each feature's SHAP value pushes the score up (+)
    or down (-) from it, and baseline + sum of SHAP values = the score.
  * mean |SHAP|: how far, on average, a feature moves the score in either
    direction. Bigger means the model leans on it more.
  * mean SHAP (signed): whether the feature mostly raises or lowers scores
    across the test set. Positive and negative effects can cancel, which is
    why the absolute value is used for ranking.
  * It describes how THIS model behaves on its simulated data. It is not proof
    that a feature causes food insecurity in real households.
"""

import json

import numpy as np
import pandas as pd

from .predictor import RiskPredictor
from .registry import digest, version_directory

FILENAME = "global_explanation.json"


def test_rows(version):
    """The model's held-out test records, as feature frames for its own contract."""
    from .train_simulated import load_dataframe

    membership = pd.read_csv(version_directory(version) / "split_membership.csv")
    test_ids = set(membership.loc[membership.split == "test", "household_id"])
    data = load_dataframe()
    return data[data.household_id.isin(test_ids)]


def compute(version):
    predictor = RiskPredictor(version)
    if predictor.contract.SCHEMA_VERSION != "simulated-household-v1":
        raise ValueError("Model-wide summaries are only produced for the simulated-data model")
    rows = test_rows(version)
    contributions, scores = [], []
    for _, row in rows.iterrows():
        snapshot = {name: row[name] for name in predictor.contract.FEATURE_COLS}
        for name in predictor.contract.NUMERIC_FEATURES:
            snapshot[name] = float(snapshot[name])
        contributions.append(predictor.explain(snapshot))
        scores.append(predictor.model.predict_proba(_frame(predictor, snapshot))[0][1])
    table = pd.DataFrame(contributions)
    baseline = float(np.asarray(predictor.explainer.expected_value).reshape(-1)[-1])
    return {
        "model_version": version,
        "artifact_sha256": predictor.artifact_sha256,
        "manifest_sha256": digest(version_directory(version) / "manifest.json"),
        "records": len(table),
        "record_source": "held-out simulated test split (split_membership.csv)",
        "baseline_probability": round(baseline, 6),
        "mean_test_probability": round(float(np.mean(scores)), 6),
        "mean_absolute_shap": {
            k: round(float(v), 6) for k, v in table.abs().mean().sort_values(ascending=False).items()
        },
        "mean_shap": {k: round(float(v), 6) for k, v in table.mean().items()},
        "notice": (
            "Describes how this simulated-data model behaves on its held-out simulated test records. "
            "Associations, not causes; not validated on real households."
        ),
    }


def _frame(predictor, snapshot):
    from .predictor import feature_frame

    return feature_frame(snapshot, predictor.contract)


def write(version):
    summary = compute(version)
    path = version_directory(version) / FILENAME
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path, summary


def load(version):
    """The stored summary for a model version, or None if it is missing or belongs to another artifact."""
    try:
        directory = version_directory(version)
        summary = json.loads((directory / FILENAME).read_text(encoding="utf-8"))
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if summary.get("artifact_sha256") != manifest.get("artifact_sha256"):
        return None  # computed for a different model file: never show it
    return summary
