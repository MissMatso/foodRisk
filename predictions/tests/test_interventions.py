from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from accounts.models import CustomUser
from households.models import Household
from predictions.models import Intervention, Prediction


class InterventionWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(
            username="intervention_staff", password="pw12345!", role="staff"
        )
        cls.analyst = CustomUser.objects.create_user(
            username="intervention_analyst", password="pw12345!", role="analyst"
        )
        cls.household = Household.objects.create(
            name="Follow-up Household",
            address="1 Test Ave",
            contact="0111111111",
            monthly_income=2000,
            household_size=3,
            num_dependents=1,
            employment_status="unemployed",
            registered_by=cls.staff,
        )
        cls.prediction = Prediction.objects.create(
            household=cls.household, score=82, category="High", model_version="test", generated_by=cls.staff
        )

    def test_staff_can_record_intervention(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("predictions:intervention", args=[self.prediction.pk]),
            {
                "action": "urgent_referral",
                "notes": "Food parcel referral",
                "follow_up_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "status": "open",
            },
        )
        self.assertRedirects(response, reverse("predictions:detail", args=[self.prediction.pk]))
        item = Intervention.objects.get(prediction=self.prediction)
        self.assertEqual(item.created_by, self.staff)
        self.assertEqual(item.follow_up_date, timezone.localdate() + timedelta(days=7))

    def test_analyst_cannot_record_intervention(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("predictions:intervention", args=[self.prediction.pk]))
        self.assertEqual(response.status_code, 403)

    def test_staff_completes_existing_intervention(self):
        item = Intervention.objects.create(
            prediction=self.prediction, action="monitor", created_by=self.staff
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("predictions:intervention_edit", args=[item.pk]),
            {
                "action": "monitor",
                "notes": "Follow-up completed",
                "status": "completed",
                "follow_up_date": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "completed")
        self.assertEqual(Intervention.objects.count(), 1)
        self.assertEqual(item.created_by, self.staff)

    def test_analyst_cannot_update(self):
        item = Intervention.objects.create(
            prediction=self.prediction, action="monitor", created_by=self.staff
        )
        self.client.force_login(self.analyst)
        self.assertEqual(
            self.client.post(
                reverse("predictions:intervention_edit", args=[item.pk]),
                {"action": "monitor", "status": "completed"},
            ).status_code,
            403,
        )
        item.refresh_from_db()
        self.assertEqual(item.status, "open")

    def test_invalid_action_not_saved(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("predictions:intervention", args=[self.prediction.pk]),
            {"action": "invalid", "status": "open"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Intervention.objects.exists())
