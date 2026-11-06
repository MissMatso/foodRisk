"""Real-data lineage, model lifecycle, encrypted explanations and RBAC regression tests."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction
from predictions.services import explain_prediction, save_prediction
from .features import FEATURE_COLS, from_household
from .ghs_data import load_ghs
from .monitoring import compare_profile, reference_profile
from .predictor import RiskPredictor, feature_frame
from .registry import resolve_bundle, version_directory
from .train_model import split_data


@override_settings(DEBUG=True, FOODRISK_MODEL_VERSION="ghs2024_rf_v3")
class ModelIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.household = Household.objects.create(
            name="Model integration",
            address="Test",
            contact="0840000000",
            monthly_income="2400.00",
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
            children_under_5=1,
            elderly_members=1,
            water_access="communal",
        )
        cls.user = CustomUser.objects.create_user(username="modelstaff", role="staff")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.predictor = RiskPredictor()

    def prediction(self):
        return save_prediction(self.household, self.predictor.predict(self.household), self.user)

    def test_saved_model_scores_and_explains_registered_household(self):
        result = self.predictor.predict(self.household)
        self.assertNotIn("error", result)
        self.assertTrue(0 <= result["score"] <= 100)
        explanation = self.predictor.explain(result["input_snapshot"])
        self.assertEqual(set(explanation), set(FEATURE_COLS))
        expected = np.asarray(self.predictor.explainer.expected_value)[1]
        probability = self.predictor.model.predict_proba(feature_frame(result["input_snapshot"]))[0, 1]
        self.assertAlmostEqual(sum(explanation.values()) + expected, probability, places=6)

    def test_unknown_income_is_imputed_and_high_income_is_capped(self):
        self.household.monthly_income = None
        result = self.predictor.predict(self.household)
        self.assertNotIn("error", result)
        self.assertIsNone(result["input_snapshot"]["monthly_income"])
        self.household.monthly_income = 50000
        self.assertEqual(from_household(self.household)["monthly_income"], 20000)

    def test_original_snapshot_survives_household_edit_and_is_encrypted(self):
        prediction = self.prediction()
        original = prediction.input_snapshot
        self.household.monthly_income = 9000
        self.household.save()
        with patch("predictions.services.get_predictor", return_value=self.predictor), patch.object(
            self.predictor, "explain", return_value={"monthly_income": 0.1}
        ) as explain:
            explain_prediction(prediction)
            self.assertEqual(explain.call_args.args[0]["monthly_income"], 2400.0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT input_snapshot FROM predictions_prediction WHERE id=%s", [prediction.pk])
            raw = cursor.fetchone()[0]
        self.assertNotEqual(raw, original)
        self.assertNotIn("monthly_income", raw)

    def test_explanation_is_cached_per_prediction(self):
        prediction = self.prediction()
        prediction.explanation = {"monthly_income": 0.1}
        prediction.save()
        with patch("predictions.services.get_predictor") as predictor:
            self.assertEqual(explain_prediction(prediction), {"monthly_income": 0.1})
            predictor.assert_not_called()

    def test_explanation_failure_preserves_score(self):
        prediction = self.prediction()
        with patch("predictions.services.get_predictor", return_value=self.predictor), patch.object(
            self.predictor, "explain", side_effect=RuntimeError("SHAP unavailable")
        ):
            self.client.force_login(self.user)
            response = self.client.post(reverse("api-predictions-explain", args=[prediction.pk]))
        self.assertEqual(response.status_code, 422)
        prediction.refresh_from_db()
        self.assertIsNone(prediction.explanation)
        self.assertEqual(Prediction.objects.count(), 1)

    def test_mismatched_artifact_and_legacy_snapshot_rejected(self):
        prediction = self.prediction()
        prediction.artifact_sha256 = "0" * 64
        with self.assertRaises(ValueError):
            explain_prediction(prediction)
        prediction.input_snapshot = None
        with self.assertRaisesMessage(ValueError, "older prediction"):
            explain_prediction(prediction)

    def test_explanation_permissions_csrf_and_snapshot_not_in_api(self):
        prediction = self.prediction()
        analyst = CustomUser.objects.create_user(username="modelanalyst", role="analyst")
        url = reverse("api-predictions-explain", args=[prediction.pk])
        self.client.force_login(analyst)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("predictions:explain", args=[prediction.pk])).status_code, 403
        )
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.user)
        self.assertEqual(secure_client.post(url).status_code, 403)
        with patch("predictions.services.explain_prediction"):
            response = self.client.get(reverse("api-predictions-detail", args=[prediction.pk]))
        self.assertNotIn("input_snapshot", response.json())
        with patch("predictions.services.get_predictor", return_value=self.predictor), patch.object(
            self.predictor, "explain", return_value={"monthly_income": 0.2}
        ):
            self.assertEqual(self.client.post(url).status_code, 200)
        prediction.refresh_from_db()
        self.assertIsNotNone(prediction.explanation_generated_at)


@override_settings(FOODRISK_MODEL_VERSION="ghs2024_rf_v3")
class DatasetTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.df, cls.audit = load_ghs()

    def test_real_missing_codes_and_known_outcomes(self):
        self.assertEqual(self.audit["households"], 20940)
        self.assertEqual(self.audit["people"], 70440)
        self.assertEqual(self.audit["raw_income_unspecified"], 433)
        self.assertEqual(self.audit["excluded_target_rows"], 29)
        self.assertEqual(len(self.df), 20911)
        self.assertEqual(set(self.df.reported_food_shortage), {0, 1})
        self.assertFalse(self.df.monthly_income.eq(9999999).any())
        self.assertTrue(self.df.monthly_income.isna().any())

    def test_psu_groups_do_not_leak_between_splits(self):
        splits = split_data(self.df)
        a, b, c = (set(splits[n].psu) for n in ("train", "validation", "test"))
        self.assertFalse(a & b or a & c or b & c)
        self.assertEqual(sum(len(v) for v in splits.values()), len(self.df))

    def test_imputer_fitted_only_to_training_income(self):
        _, manifest = resolve_bundle(serving=False)
        import joblib

        artifact, _ = resolve_bundle(serving=False)
        model = joblib.load(artifact)
        median = split_data(self.df)["train"].monthly_income.median()
        learned = (
            model.named_steps["preprocessor"].named_transformers_["num"].named_steps["impute"].statistics_[0]
        )
        self.assertEqual(learned, median)
        self.assertFalse(manifest["validation"]["ngo_external_validation"])

    def test_drift_screen_same_shifted_and_small_batches(self):
        df = self.df[FEATURE_COLS].copy()
        reference = reference_profile(df)
        self.assertEqual(compare_profile(df, reference)["status"], "no_alert")
        self.assertEqual(compare_profile(df.iloc[:20], reference)["status"], "insufficient_data")
        df["monthly_income"] = 100000
        self.assertEqual(compare_profile(df, reference)["status"], "review")


class RegistryTests(TestCase):
    def test_invalid_version_and_overwrite_rejected(self):
        with self.assertRaises(ValueError):
            version_directory("../model")
        with self.assertRaises(FileExistsError):
            from .train_model import main

            main("ghs2024_rf_v3")

    @override_settings(DEBUG=False)
    def test_unapproved_candidate_cannot_serve_operationally(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            resolve_bundle()

    def test_checksum_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp) / "candidate"
            d.mkdir()
            _, original = resolve_bundle(serving=False)
            manifest = {**original, "model_version": "candidate"}
            (d / "manifest.json").write_text(json.dumps(manifest))
            (d / "model.joblib").write_bytes(b"tampered")
            with override_settings(MODEL_REGISTRY_ROOT=Path(temp)):
                with self.assertRaisesMessage(ValueError, "checksum mismatch"):
                    resolve_bundle("candidate", serving=False)

    def test_operational_approval_requires_external_validation(self):
        CustomUser.objects.create_user(username="reviewer", role="admin")
        with self.assertRaisesMessage(CommandError, "external NGO validation"):
            call_command(
                "approve_model",
                model_version="ghs2024_rf_v3",
                reviewer="reviewer",
                scope="operational",
                evidence="README.md",
                notes="Test",
            )
