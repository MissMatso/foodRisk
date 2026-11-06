"""Scoring failures must not become saved or misleading assessments."""

from decimal import Decimal
from unittest.mock import MagicMock
from django.test import TestCase
from households.models import Household
from ml_engine.predictor import RiskPredictor
from ml_engine import simulated_features


class PredictionFallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.household = Household.objects.create(
            name="Fallback",
            address="Test",
            contact="0111111111",
            monthly_income=Decimal("2000"),
            household_size=3,
            num_dependents=1,
            employment_status="unemployed",
        )

    def predictor(self):
        predictor = RiskPredictor.__new__(RiskPredictor)
        predictor.model = MagicMock()
        predictor.model.predict_proba.return_value = [[0.2, 0.8]]
        predictor.version = "test"
        predictor.artifact_sha256 = "a" * 64
        predictor.contract = simulated_features
        return predictor

    def test_missing_required_feature_returns_message(self):
        self.household.household_size = None
        result = self.predictor().predict(self.household)
        self.assertEqual(result["error"], "Missing feature: household_size. Please update household data.")

    def test_model_inference_failure_returns_exact_message(self):
        predictor = self.predictor()
        predictor.model.predict_proba.side_effect = RuntimeError("boom")
        self.assertEqual(predictor.predict(self.household), {"error": "Prediction unavailable."})

    def test_successful_prediction_skips_explanation(self):
        predictor = self.predictor()
        predictor.explain = MagicMock(side_effect=AssertionError("Must not explain while scoring"))
        result = predictor.predict(self.household)
        self.assertEqual(result["score"], 80.0)
        self.assertEqual(result["category"], "High")
        self.assertIsNone(result["explanation"])
        self.assertEqual(result["input_snapshot"]["monthly_income"], 2000.0)
        predictor.explain.assert_not_called()
