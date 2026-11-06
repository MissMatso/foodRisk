"""Aggregate input-drift screening; alerts require review, never automatic retraining."""

import numpy as np
from .features import CATEGORICAL_FEATURES, NUMERIC_FEATURES


def reference_profile(df, numeric_features=NUMERIC_FEATURES, categorical_features=CATEGORICAL_FEATURES):
    result = {}
    for name in numeric_features:
        series = df[name].dropna().astype(float)
        cuts = np.unique(np.quantile(series, np.arange(0.1, 1, 0.1)))
        proportions = np.histogram(series, bins=np.r_[-np.inf, cuts, np.inf])[0] / len(series)
        result[name] = {
            "kind": "numeric",
            "cuts": cuts.tolist(),
            "proportions": proportions.tolist(),
            "min": float(series.min()),
            "max": float(series.max()),
            "missing": float(df[name].isna().mean()),
        }
    for name in categorical_features:
        result[name] = {
            "kind": "categorical",
            "proportions": df[name].dropna().astype(str).value_counts(normalize=True).to_dict(),
            "missing": float(df[name].isna().mean()),
        }
    return result


def compare_profile(df, reference, min_rows=100):
    if len(df) < min_rows:
        return {"status": "insufficient_data", "rows": len(df), "minimum_rows": min_rows, "features": {}}
    results = {}
    for name, ref in reference.items():
        series = df[name].dropna()
        missing_delta = abs(float(df[name].isna().mean()) - ref["missing"])
        if ref["kind"] == "numeric":
            values = series.astype(float)
            current = np.histogram(values, bins=np.r_[-np.inf, ref["cuts"], np.inf])[0] / max(len(values), 1)
            variation = float(np.abs(current - ref["proportions"]).sum() / 2)
            unseen = float((~values.between(ref["min"], ref["max"])).mean()) if len(values) else 0.0
        else:
            current = series.astype(str).value_counts(normalize=True).to_dict()
            keys = set(current) | set(ref["proportions"])
            variation = sum(abs(current.get(k, 0) - ref["proportions"].get(k, 0)) for k in keys) / 2
            unseen = float(sum(v for k, v in current.items() if k not in ref["proportions"]))
        results[name] = {
            "total_variation": variation,
            "missing_rate_delta": missing_delta,
            "unseen_or_outside_range": unseen,
            "alert": variation > 0.2 or missing_delta > 0.1 or unseen > 0.05,
        }
    return {
        "status": "review" if any(r["alert"] for r in results.values()) else "no_alert",
        "rows": len(df),
        "features": results,
        "policy": (
            "Review if variation >0.20, missing-rate change >0.10, or "
            "unseen/out-of-range >0.05. Screening thresholds are provisional, not "
            "validation of performance."
        ),
    }
