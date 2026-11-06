"""A score is out of date when the household's data changed after it was calculated."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction
from predictions.services import inputs_changed_since

PASSWORD = "pw12345!"


@override_settings(DEBUG=True)  # the research model is only served in debug mode
class StaleScoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")

    def setUp(self):
        self.household = Household.objects.create(
            name="Stale Family",
            address="1 Main Rd",
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
        )
        self.client.login(username="staff1", password=PASSWORD)
        self.client.post(reverse("predictions:generate", args=[self.household.pk]))
        self.detail_url = reverse("households:household_detail", args=[self.household.pk])

    def edit(self, **changes):
        self.household.refresh_from_db()
        for field, value in changes.items():
            setattr(self.household, field, value)
        self.household.save()

    def test_a_fresh_score_is_not_flagged(self):
        self.assertNotContains(self.client.get(self.detail_url), "Out of date")
        self.assertNotContains(self.client.get(reverse("dashboard:risk_dashboard")), "Out of date")

    def test_changing_a_model_input_flags_the_score_on_the_household_page_and_dashboard(self):
        self.edit(monthly_income=40000)
        self.assertContains(self.client.get(self.detail_url), "Out of date")
        self.assertContains(self.client.get(reverse("dashboard:risk_dashboard")), "Out of date")

    def test_changing_something_the_model_does_not_use_does_not_flag_it(self):
        self.edit(name="Renamed Family", contact="083 999 0000", address="9 Other St")
        self.assertNotContains(self.client.get(self.detail_url), "Out of date")

    def test_generating_a_new_score_clears_the_warning(self):
        self.edit(household_size=7)
        self.assertContains(self.client.get(self.detail_url), "Out of date")
        self.client.post(reverse("predictions:generate", args=[self.household.pk]))
        self.assertNotContains(self.client.get(self.detail_url), "Out of date")
        self.assertEqual(Prediction.objects.filter(household=self.household).count(), 2)

    def test_an_analyst_sees_the_warning_but_is_not_told_to_generate_a_score(self):
        self.edit(household_size=7)
        self.client.login(username="analyst1", password=PASSWORD)
        html = self.client.get(self.detail_url).content.decode()
        self.assertIn("Out of date", html)
        self.assertNotIn("Generate a new score", html)

    def test_an_older_score_without_a_snapshot_falls_back_to_the_edit_time(self):
        Prediction.objects.update(input_snapshot=None)
        prediction = Prediction.objects.get()
        self.household.refresh_from_db()
        self.assertFalse(inputs_changed_since(prediction, self.household))
        self.edit(name="Touched")
        self.assertTrue(inputs_changed_since(prediction, self.household))

    def test_a_check_that_cannot_run_never_breaks_the_page(self):
        Prediction.objects.update(feature_schema="no_such_schema")
        self.edit(household_size=7)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:risk_dashboard")).status_code, 200)
        with patch("predictions.services.get_contract", side_effect=RuntimeError("boom")):
            prediction = Prediction.objects.get()
            self.assertFalse(inputs_changed_since(prediction, self.household))
