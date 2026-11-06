"""Restored dataset, active model and cross-schema history regressions."""

import numpy as np
from django.test import TestCase, override_settings
from accounts.models import CustomUser
from households.models import Household
from predictions.services import save_prediction, explain_prediction
from . import simulated_features
from .predictor import RiskPredictor, feature_frame
from .registry import digest
from .train_simulated import DATA_PATH, load_dataframe, split_data


@override_settings(DEBUG=True, FOODRISK_MODEL_VERSION="simulated_rf_v2")
class RestoredDatasetTests(TestCase):
    def test_original_csv_is_unchanged_and_labels_are_explicit(self):
        self.assertEqual(
            digest(DATA_PATH), "69ca747f2c58e90fb3c1939b58136b80da64c4ba43e8cb22994afc3b8967d888"
        )
        df = load_dataframe()
        self.assertEqual(len(df), 10000)
        self.assertEqual(int(df[simulated_features.TARGET].sum()), 4726)
        splits = split_data(df)
        a, b, c = (set(splits[n].household_id) for n in ("train", "validation", "test"))
        self.assertFalse(a & b or a & c or b & c)
        self.assertEqual([len(splits[n]) for n in ("train", "validation", "test")], [6000, 2000, 2000])

    def test_active_model_and_optional_explanations(self):
        user = CustomUser.objects.create_user(username="restorestaff", role="staff")
        hh = Household.objects.create(
            name="Demonstration",
            address="Demo",
            contact="0000000000",
            household_size=5,
            num_dependents=4,
            children_under_5=1,
            elderly_members=1,
            monthly_income=None,
            employment_status="unemployed",
            water_access="other",
        )
        predictor = RiskPredictor()
        result = predictor.predict(hh)
        self.assertNotIn("error", result)
        self.assertEqual(result["model_version"], "simulated_rf_v2")
        self.assertIsNone(result["explanation"])
        self.assertIsNone(result["input_snapshot"]["monthly_income"])
        self.assertEqual(result["input_snapshot"]["num_dependents"], 2)
        pred = save_prediction(hh, result, user)
        contribution = explain_prediction(pred)
        self.assertEqual(set(contribution), set(simulated_features.FEATURE_COLS))
        expected = predictor.model.predict_proba(feature_frame(result["input_snapshot"], predictor.contract))[
            0, 1
        ]
        predictor.explain(result["input_snapshot"])
        self.assertAlmostEqual(
            sum(contribution.values()) + np.asarray(predictor.explainer.expected_value)[1], expected, places=6
        )
        hh.monthly_income = 50000
        self.assertEqual(simulated_features.from_household(hh)["monthly_income"], 50000)

    def test_previous_ghs_explanation_keeps_original_schema(self):
        hh = Household.objects.create(
            name="History",
            address="Demo",
            contact="0000000000",
            household_size=3,
            num_dependents=1,
            monthly_income=2000,
            employment_status="unemployed",
        )
        old = RiskPredictor("ghs2024_rf_v3")
        pred = save_prediction(hh, old.predict(hh), None)
        self.assertEqual(len(explain_prediction(pred)), 7)
        self.assertEqual(pred.model_version, "ghs2024_rf_v3")
