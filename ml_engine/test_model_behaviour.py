"""How the active model treats households: location, repeatability and its SHAP explanations.

These tests answer questions a reviewer is likely to ask:
  * Would a household in Cape Town get a different score from the same household in Kuruman?
    No. Ward, village and province are recorded for case work but are not model inputs.
    Place only matters through distance to market and water access.
  * Does the same household always get the same score? Yes: the forest is fixed when trained
    (random_state=42) and scoring has no randomness.
  * Do the SHAP values add up? Yes: baseline + every contribution = the score.
"""

import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from households.testing import unique_address
from ml_engine import global_explanation, simulated_features
from ml_engine.predictor import RiskPredictor
from predictions.models import Prediction

PASSWORD = "pw12345!"
CIRCUMSTANCES = dict(
    monthly_income=1800,
    household_size=5,
    num_dependents=2,
    children_under_5=1,
    elderly_members=1,
    employment_status="informal",
    has_disabled_member=False,
    has_chronic_illness=True,
    distance_to_market_km=12,
    water_access="communal",
    land_ownership=False,
)


def household(**changes):
    """An in-memory household (nothing saved), as the predictor sees it."""
    return SimpleNamespace(**{**CIRCUMSTANCES, **changes})


@override_settings(DEBUG=True)  # the research model is only served in debug mode
class LocationAndRepeatabilityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.predictor = RiskPredictor("simulated_rf_v2")  # loaded once; not copied per test

    def score(self, **changes):
        return self.predictor.predict(household(**changes))["score"]

    def test_location_fields_are_not_model_inputs(self):
        for field in ("ward", "village", "province", "address"):
            self.assertNotIn(field, simulated_features.FEATURE_COLS)

    def test_the_same_circumstances_score_the_same_in_kuruman_and_cape_town(self):
        kuruman = self.score(ward="John Taolo Gaetsewe", village="Kuruman", province="3")
        cape_town = self.score(ward="City of Cape Town", village="Cape Town", province="1")
        self.assertEqual(kuruman, cape_town)

    def test_place_matters_only_through_distance_and_water(self):
        base = self.score()
        self.assertNotEqual(base, self.score(distance_to_market_km=60, water_access="river"))

    def test_scoring_is_repeatable(self):
        first = self.score()
        self.assertEqual({self.score() for _ in range(5)}, {first})
        self.assertEqual(
            RiskPredictor("simulated_rf_v2").predict(household())["score"], first
        )  # fresh load too


@override_settings(DEBUG=True)
class ShapSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        cls.analyst = CustomUser.objects.create_user("analyst1", password=PASSWORD, role="analyst")

    def test_the_stored_summary_belongs_to_the_serving_model(self):
        summary = global_explanation.load("simulated_rf_v2")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["records"], 2000)
        self.assertEqual(set(summary["mean_absolute_shap"]), set(simulated_features.FEATURE_COLS))
        self.assertTrue(0 < summary["baseline_probability"] < 1)

    def test_a_summary_for_another_model_file_is_never_shown(self):
        source = global_explanation.version_directory("simulated_rf_v2")
        with tempfile.TemporaryDirectory() as registry:
            copy = Path(registry) / "simulated_rf_v2"
            copy.mkdir()
            shutil.copy(source / "manifest.json", copy / "manifest.json")
            summary = json.loads((source / global_explanation.FILENAME).read_text(encoding="utf-8"))
            summary["artifact_sha256"] = "0" * 64  # as if computed for an older model file
            (copy / global_explanation.FILENAME).write_text(json.dumps(summary), encoding="utf-8")
            with self.settings(MODEL_REGISTRY_ROOT=registry):
                self.assertIsNone(global_explanation.load("simulated_rf_v2"))
        self.assertIsNone(global_explanation.load("model_that_does_not_exist"))

    def test_baseline_plus_contributions_equals_the_score(self):
        record = Household.objects.create(
            name="Additive Family", address=unique_address(), contact="071 111 2222", **CIRCUMSTANCES
        )
        self.client.force_login(self.staff)
        self.client.post(reverse("predictions:generate", args=[record.pk]))
        prediction = Prediction.objects.get(household=record)
        self.client.post(reverse("predictions:explain", args=[prediction.pk]))
        page = self.client.get(reverse("predictions:detail", args=[prediction.pk]))
        self.assertAlmostEqual(page.context["explained_percent"], prediction.score, delta=0.1)
        self.assertContains(page, "baseline of")
        self.assertContains(page, "Income per person")  # plain-English feature names

    def test_the_report_shows_the_model_wide_table_clearly_labelled(self):
        self.client.force_login(self.analyst)
        page = self.client.get(reverse("dashboard:risk_reports"))
        self.assertContains(page, "held-out simulated test records")
        self.assertContains(page, "not causes")
        rows = page.context["global_explanation"]["rows"]
        self.assertEqual(rows[0]["label"], "Income per person")
        self.assertAlmostEqual(sum(row["share"] for row in rows), 100, delta=0.5)
