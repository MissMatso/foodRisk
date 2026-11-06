"""Shared persistence rules for web, API and demo prediction workflows."""

import json
from datetime import timedelta

from django.utils import timezone
from ml_engine.feature_contracts import get_contract
from ml_engine.predictor import get_predictor
from ml_engine.registry import resolve_bundle
from .models import Prediction

RECENT_ASSESSMENT_SECONDS = 30


def inputs_changed_since(prediction, household):
    """True when the household's data no longer matches what this score was worked out from.

    Only the model's own inputs count, so editing a name or a phone number does not make a
    score out of date. A score saved before snapshots existed falls back to the edit time.
    """
    try:
        if prediction.input_snapshot:
            current = get_contract(prediction.feature_schema).from_household(household)
            return json.loads(json.dumps(current)) != json.loads(prediction.input_snapshot)
        return household.updated_at > prediction.created_at
    except Exception:  # a check that cannot run must never break the page it decorates
        return False


def recent_assessment(household, seconds=RECENT_ASSESSMENT_SECONDS):
    """A score created moments ago for unchanged data (a double click), else None.

    If the household was edited after that score, a new score is legitimate.
    """
    latest = household.predictions.order_by("-created_at").first()
    if latest is None:
        return None
    if timezone.now() - latest.created_at > timedelta(seconds=seconds):
        return None
    if household.updated_at > latest.created_at:
        return None
    return latest


def save_prediction(household, result, user):
    return Prediction.objects.create(
        household=household,
        score=result["score"],
        category=result["category"],
        model_version=result["model_version"],
        explanation=result.get("explanation"),
        generated_by=user,
        input_snapshot=(
            json.dumps(result["input_snapshot"], allow_nan=False) if result.get("input_snapshot") else None
        ),
        artifact_sha256=result.get("artifact_sha256", ""),
        feature_schema=result.get("feature_schema", ""),
    )


def explain_prediction(prediction):
    if prediction.explanation is not None:
        return prediction.explanation  # Persisted record is the cache boundary.
    if not prediction.input_snapshot or not prediction.artifact_sha256:
        raise ValueError("This older prediction has no original input snapshot; generate a new assessment.")
    _, manifest = resolve_bundle(prediction.model_version)
    if (
        manifest["artifact_sha256"] != prediction.artifact_sha256
        or manifest["feature_schema"] != prediction.feature_schema
    ):
        raise ValueError("Original model or feature schema does not match this prediction.")
    predictor = get_predictor(prediction.model_version)
    if getattr(predictor, "artifact_sha256", None) != prediction.artifact_sha256:
        raise ValueError("Cached model does not match this prediction.")
    explanation = predictor.explain(json.loads(prediction.input_snapshot))
    # Concurrent requests may compute twice; only the first persists. No distributed-lock claim.
    Prediction.objects.filter(pk=prediction.pk, explanation__isnull=True).update(
        explanation=explanation, explanation_generated_at=timezone.now()
    )
    prediction.refresh_from_db()
    return prediction.explanation
