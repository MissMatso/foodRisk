from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from accounts.models import CustomUser
from households.models import Household, AuditLog
from predictions.models import Prediction


class WorkflowRegressionTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username="workflow", password="test-pass", role="staff")
        self.client.force_login(self.user)
        self.data = dict(
            name="Test",
            address="Test address",
            contact="0123456789",
            monthly_income="1000",
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
        )

    def test_invalid_api_create_returns_400_without_writes(self):
        response = self.client.post(reverse("api-households-list"), {**self.data, "num_dependents": 7})
        self.assertEqual(response.status_code, 400)
        self.assertIn("num_dependents", response.json())
        self.assertFalse(Household.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_partial_update_checks_existing_composition(self):
        household = Household.objects.create(**self.data)
        response = self.client.patch(
            reverse("api-households-detail", args=[household.pk]),
            {"household_size": 1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        household.refresh_from_db()
        self.assertEqual(household.household_size, 4)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_audit_failure_rolls_back_create_and_update(self):
        with patch("households.audit.AuditLog.objects.create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                Household.objects.create(**self.data)
        self.assertFalse(Household.objects.exists())
        household = Household.objects.create(**self.data)
        with patch("households.audit.AuditLog.objects.create", side_effect=RuntimeError("audit failed")):
            household.name = "Changed"
            with self.assertRaises(RuntimeError):
                household.save()
        household.refresh_from_db()
        self.assertEqual(household.name, "Test")

    def test_missing_model_returns_api_error_without_prediction(self):
        household = Household.objects.create(**self.data)
        with patch("ml_engine.predictor._predictor_instance", None), patch(
            "ml_engine.predictor.RiskPredictor", side_effect=FileNotFoundError
        ):
            response = self.client.post(reverse("api-households-predict", args=[household.pk]))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"error": "Prediction unavailable."})
        self.assertFalse(Prediction.objects.exists())

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
