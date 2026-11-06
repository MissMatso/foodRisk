"""A double click or refresh on Generate Risk Score must not store the same score twice."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction

PASSWORD = "pw12345!"


@override_settings(DEBUG=True)  # the research model is only served in debug mode
class DoubleSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.household = Household.objects.create(
            name="Double Click Family",
            address="1 Main Rd",
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
        )

    def setUp(self):
        self.client.login(username="staff1", password=PASSWORD)
        self.url = reverse("predictions:generate", args=[self.household.pk])

    def count(self):
        return Prediction.objects.filter(household=self.household).count()

    def test_the_first_click_scores_and_a_second_immediate_click_does_not(self):
        self.client.post(self.url)
        self.assertEqual(self.count(), 1)
        response = self.client.post(self.url, follow=True)
        self.assertEqual(self.count(), 1)
        self.assertContains(response, "no duplicate was created")

    def test_editing_the_household_allows_a_new_score_straight_away(self):
        self.client.post(self.url)
        self.household.refresh_from_db()
        self.household.household_size = 6
        self.household.save()
        self.client.post(self.url)
        self.assertEqual(self.count(), 2)

    def test_a_later_score_for_unchanged_data_is_allowed_after_the_window(self):
        self.client.post(self.url)
        Prediction.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.client.post(self.url)
        self.assertEqual(self.count(), 2)

    def test_the_button_disables_itself_when_clicked(self):
        html = self.client.get(
            reverse("households:household_detail", args=[self.household.pk])
        ).content.decode()
        self.assertIn("disabled = true", html)
