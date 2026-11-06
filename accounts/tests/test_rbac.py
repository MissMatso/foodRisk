"""Role-based access control tests — staff vs analyst vs admin."""

from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction


class RBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password="pw12345!", role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password="pw12345!", role="staff")
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password="pw12345!", role="analyst")

    def test_staff_can_access_household_create(self):
        self.client.login(username="staff1", password="pw12345!")
        response = self.client.get(reverse("households:household_create"))
        self.assertEqual(response.status_code, 200)

    def test_analyst_cannot_access_household_create(self):
        self.client.login(username="analyst1", password="pw12345!")
        response = self.client.get(reverse("households:household_create"))
        self.assertEqual(response.status_code, 403)

    def test_analyst_can_access_reports(self):
        self.client.login(username="analyst1", password="pw12345!")
        response = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(response.status_code, 200)

    def test_staff_cannot_access_reports(self):
        self.client.login(username="staff1", password="pw12345!")
        response = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(response.status_code, 403)

    def test_only_admin_can_access_user_list(self):
        self.client.login(username="staff1", password="pw12345!")
        response = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin1", password="pw12345!")
        response = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_user_redirected_to_login(self):
        response = self.client.get(reverse("dashboard:risk_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_both_staff_and_analyst_can_view_household_list(self):
        for username in ("staff1", "analyst1"):
            self.client.login(username=username, password="pw12345!")
            response = self.client.get(reverse("households:household_list"))
            self.assertEqual(response.status_code, 200)

    def test_prediction_api_enforces_staff_role_before_inference(self):
        household = Household.objects.create(
            name="API permission check",
            address="123 Test Street",
            contact="0123456789",
            monthly_income="2000.00",
            household_size=3,
            num_dependents=1,
            employment_status="unemployed",
        )
        url = reverse("api-households-predict", args=[household.pk])
        with patch("ml_engine.api_views.get_predictor") as predictor:
            self.client.login(username="analyst1", password="pw12345!")
            self.assertEqual(self.client.post(url).status_code, 403)
            predictor.assert_not_called()
            self.assertFalse(Prediction.objects.exists())

            self.client.login(username="staff1", password="pw12345!")
            predictor.return_value.predict.return_value = {
                "score": 75,
                "category": "High",
                "model_version": "test",
                "explanation": {},
            }
            self.assertEqual(self.client.post(url).status_code, 201)
            self.assertEqual(Prediction.objects.get().generated_by, self.staff)

    def test_api_registration_records_responsible_staff_member(self):
        self.client.login(username="staff1", password="pw12345!")
        response = self.client.post(
            reverse("api-households-list"),
            data={
                "name": "API registration",
                "address": "4 Test Road",
                "contact": "0834567890",
                "monthly_income": "1500.00",
                "household_size": 4,
                "num_dependents": 2,
                "employment_status": "unemployed",
                "water_access": "piped",
            },
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Household.objects.get(pk=response.data["id"]).registered_by, self.staff)
