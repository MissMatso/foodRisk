"""Direct checks for business rules BR-04 and BR-05 and the FR006 score bands."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from ml_engine.predictor import RiskPredictor
from predictions.models import Prediction
from predictions.services import save_prediction
from households.testing import unique_address

MODEL = settings.FOODRISK_MODEL_VERSION


def make_household(name):
    return Household.objects.create(
        name=name,
        address=unique_address("Private Street"),
        contact="0123456789",
        monthly_income=2000,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )


class ScoreBandTests(TestCase):
    """FR006: Low is 0-33, Medium 34-66, High 67-100 (on the rounded score)."""

    def test_band_edges(self):
        bands = RiskPredictor._categorize
        self.assertEqual([bands(s) for s in (0, 33)], ["Low", "Low"])
        self.assertEqual([bands(s) for s in (34, 66)], ["Medium", "Medium"])
        self.assertEqual([bands(s) for s in (67, 100)], ["High", "High"])


class PredictionRecordTests(TestCase):
    """BR-04: each score is its own record, linked to exactly one household, with a version and time."""

    def test_each_score_is_a_separate_linked_record(self):
        household = make_household("Linked Family")
        staff = CustomUser.objects.create_user(username="staff1", role="staff")
        result = {"score": 40.0, "category": "Medium", "model_version": MODEL}
        first = save_prediction(household, result, staff)
        second = save_prediction(household, {**result, "score": 70.0, "category": "High"}, staff)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(household.predictions.count(), 2)  # history is kept, not overwritten
        for saved in (first, second):
            self.assertEqual((saved.household, saved.model_version), (household, MODEL))
            self.assertIsNotNone(saved.created_at)

    def test_a_prediction_cannot_exist_without_a_household(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Prediction.objects.create(household=None, score=10, category="Low", model_version=MODEL)


class DashboardCurrentVersionTests(TestCase):
    """BR-05: the dashboard shows the latest prediction of the configured model version only."""

    def test_latest_current_version_prediction_wins_and_other_versions_show_nothing(self):
        staff = CustomUser.objects.create_user(username="staff1", role="staff")
        mixed = make_household("Mixed Family")
        only_old = make_household("Old Only Family")
        Prediction.objects.create(household=mixed, score=90, category="High", model_version="older_model")
        Prediction.objects.create(household=mixed, score=20, category="Low", model_version=MODEL)
        Prediction.objects.create(household=only_old, score=95, category="High", model_version="older_model")

        self.client.force_login(staff)
        rows = {h.name: h for h in self.client.get(reverse("dashboard:risk_dashboard")).context["households"]}
        self.assertEqual(
            (rows["Mixed Family"].latest_score, rows["Mixed Family"].latest_category), (20, "Low")
        )
        self.assertIsNone(rows["Old Only Family"].latest_score)  # no current-version score, so none shown
