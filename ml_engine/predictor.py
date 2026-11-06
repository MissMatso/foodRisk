"""Fast scoring with separately requested, cached-by-record TreeSHAP explanations."""

import logging
import threading
import time

import joblib
import numpy as np
import pandas as pd
from django.conf import settings

from . import features
from .feature_contracts import get_contract
from .registry import resolve_bundle

logger = logging.getLogger(__name__)
MAX_PREDICTION_SECONDS = 5


def feature_frame(snapshot, contract=features):
    if set(snapshot) != set(contract.FEATURE_COLS):
        raise ValueError("Snapshot schema mismatch")
    frame = pd.DataFrame([snapshot], columns=contract.FEATURE_COLS)
    for name in contract.NUMERIC_FEATURES:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
    # The persisted imputers recognise NaN, not Python None in object columns.
    return frame.fillna(np.nan)


class RiskPredictor:
    def __init__(self, version=None):
        artifact, self.manifest = resolve_bundle(version)
        self.contract = get_contract(self.manifest["feature_schema"])
        self.model = joblib.load(artifact)  # Only administrator-controlled artifacts.
        self.version = self.manifest["model_version"]
        self.artifact_sha256 = self.manifest["artifact_sha256"]
        self.explainer = None
        self._explanation_lock = threading.Lock()

    def predict(self, household):
        start = time.perf_counter()
        try:
            snapshot = self.contract.from_household(household)
            probability = self.model.predict_proba(feature_frame(snapshot, self.contract))[0][1]
            score = round(float(probability) * 100, 2)
            elapsed = time.perf_counter() - start
            # This is detection after scoring, not a pre-emptive execution timeout.
            if elapsed > MAX_PREDICTION_SECONDS:
                raise TimeoutError("Scoring exceeded five seconds")
            return {
                "score": score,
                "category": self._categorize(score),
                "explanation": None,
                "model_version": self.version,
                "artifact_sha256": self.artifact_sha256,
                "feature_schema": self.contract.SCHEMA_VERSION,
                "input_snapshot": snapshot,
                "elapsed_seconds": elapsed,
            }
        except KeyError as exc:
            missing = exc.args[0] if exc.args else "unknown"
            return {"error": f"Missing feature: {missing}. Please update household data."}
        except Exception:
            logger.exception("Prediction failed")
            return {"error": "Prediction unavailable."}

    @staticmethod
    def _categorize(score):
        if score <= 33:
            return "Low"
        return "Medium" if score <= 66 else "High"

    def explain(self, snapshot):
        with self._explanation_lock:
            if self.explainer is None:
                import shap  # Import and initialise only for explicit explanation requests.

                self.explainer = shap.TreeExplainer(self.model.named_steps["classifier"])
            preprocessor = self.model.named_steps["preprocessor"]
            transformed = preprocessor.transform(feature_frame(snapshot, self.contract))
            if hasattr(transformed, "toarray"):
                transformed = transformed.toarray()
            values = self.explainer.shap_values(transformed)
            if isinstance(values, list):
                row = np.asarray(values[1])[0]
            else:
                values = np.asarray(values)
                row = values[0, :, 1] if values.ndim == 3 else values[0]
            grouped = {name: 0.0 for name in self.contract.FEATURE_COLS}
            for output, value in zip(preprocessor.get_feature_names_out(), row, strict=True):
                suffix = output.split("__", 1)[1]
                if suffix.startswith("missingindicator_"):
                    source = suffix.removeprefix("missingindicator_")
                else:
                    source = next(
                        (
                            name
                            for name in sorted(self.contract.FEATURE_COLS, key=len, reverse=True)
                            if suffix == name or suffix.startswith(name + "_")
                        ),
                        None,
                    )
                if source not in grouped:
                    raise ValueError("Unmapped SHAP feature")
                grouped[source] += float(value)
            return grouped


_predictor_instance = None
_version_instances = {}
_load_lock = threading.Lock()


def get_predictor(version=None):
    """One lazy instance per process/version; configuration changes require restart."""
    global _predictor_instance
    with _load_lock:
        try:
            if version is None or version == settings.FOODRISK_MODEL_VERSION:
                if _predictor_instance is None:
                    _predictor_instance = RiskPredictor()
                return _predictor_instance
            if version not in _version_instances:
                _version_instances[version] = RiskPredictor(version)
            return _version_instances[version]
        except Exception:
            logger.exception("Could not load prediction model")
            return UnavailablePredictor()


class UnavailablePredictor:
    def predict(self, household):
        return {"error": "Prediction unavailable."}

    def explain(self, snapshot):
        raise ValueError("Explanation model unavailable")
