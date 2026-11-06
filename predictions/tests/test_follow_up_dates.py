"""Follow-up dates (FR013): an open action cannot be scheduled in the past; dates show one format."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from households.models import Household
from households.testing import unique_address
from predictions.models import Intervention, Prediction

PASSWORD = "pw12345!"


class FollowUpDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        household = Household.objects.create(
            name="Dates Family",
            address=unique_address(),
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=0,
            employment_status="unemployed",
        )
        cls.prediction = Prediction.objects.create(
            household=household, score=80, category="High", model_version="x"
        )

    def setUp(self):
        self.client.force_login(self.staff)
        self.today = timezone.localdate()

    def record(self, **data):
        return self.client.post(
            reverse("predictions:intervention", args=[self.prediction.pk]),
            {"action": "urgent_referral", "notes": "", "status": "open", **data},
        )

    def test_an_open_action_cannot_be_scheduled_in_the_past(self):
        response = self.record(follow_up_date=(self.today - timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be in the past")
        self.assertFalse(Intervention.objects.exists())

    def test_today_or_later_is_accepted(self):
        for days in (0, 7):
            response = self.record(follow_up_date=(self.today + timedelta(days=days)).isoformat())
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Intervention.objects.count(), 2)

    def test_a_completed_action_may_carry_a_past_date(self):
        response = self.record(
            status="completed", follow_up_date=(self.today - timedelta(days=3)).isoformat()
        )
        self.assertEqual(response.status_code, 302)

    def test_an_overdue_action_can_still_be_updated_and_completed(self):
        overdue = Intervention.objects.create(
            prediction=self.prediction, action="monitor", follow_up_date=self.today - timedelta(days=10)
        )
        url = reverse("predictions:intervention_edit", args=[overdue.pk])
        data = {
            "action": "monitor",
            "notes": "Visited",
            "status": "open",
            "follow_up_date": overdue.follow_up_date,
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)  # unchanged date: notes can be added
        self.assertEqual(self.client.post(url, {**data, "status": "completed"}).status_code, 302)
        overdue.refresh_from_db()
        self.assertEqual((overdue.notes, overdue.status), ("Visited", "completed"))

    def test_follow_up_dates_use_the_same_format_as_other_dates(self):
        Intervention.objects.create(prediction=self.prediction, action="monitor", follow_up_date=self.today)
        page = self.client.get(reverse("predictions:detail", args=[self.prediction.pk]))
        self.assertContains(page, self.today.strftime("%d %b %Y"))

    def test_the_registration_form_uses_plain_labels(self):
        page = self.client.get(reverse("households:household_create"))
        for label in (
            "Number of dependents",
            "Distance to the nearest market (km)",
            "The household owns land",
        ):
            self.assertContains(page, label)
        self.assertNotContains(page, "Num dependents")
