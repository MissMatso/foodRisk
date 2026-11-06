"""Finding a household by phone number, and flagging scores built on an estimated income."""

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction
from households.testing import unique_address

PASSWORD = "pw12345!"


def make(**overrides):
    data = dict(
        name="Dlamini Household",
        address=unique_address(),
        contact="071 111 2222",
        ward="Hantam",
        village="Calvinia",
        monthly_income=900,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )
    return Household.objects.create(**{**data, **overrides})


class PhoneSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        CustomUser.objects.create_user("analyst1", password=PASSWORD, role="analyst")

    def search(self, user, text):
        self.client.login(username=user, password=PASSWORD)
        response = self.client.get(reverse("households:household_list"), {"q": text})
        return list(response.context["households"])

    def test_staff_find_a_household_by_phone_in_any_format(self):
        household = make()
        make(name="Other Family", contact="072 999 8888")
        for text in ("071 111 2222", "0711112222", "+27 71 111 2222"):
            self.assertEqual(self.search("staff1", text), [household], text)

    def test_name_search_still_works(self):
        household = make()
        self.assertEqual(self.search("staff1", "dlamini"), [household])

    def test_unknown_or_partial_numbers_find_nothing(self):
        make()
        self.assertEqual(self.search("staff1", "071 111 9999"), [])
        self.assertEqual(self.search("staff1", "0711"), [])

    def test_analysts_cannot_use_search_to_find_phone_numbers(self):
        make()
        self.assertEqual(self.search("analyst1", "071 111 2222"), [])


@override_settings(DEBUG=True)  # the research model is only served in debug mode
class EstimatedIncomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")

    def score(self, household):
        self.client.login(username="staff1", password=PASSWORD)
        self.client.post(reverse("predictions:generate", args=[household.pk]))
        return Prediction.objects.filter(household=household).latest("created_at")

    def test_blank_income_is_flagged_on_the_prediction_and_household_pages(self):
        prediction = self.score(make(monthly_income=None))
        self.assertTrue(prediction.income_was_estimated)
        detail = self.client.get(reverse("predictions:detail", args=[prediction.pk])).content.decode()
        self.assertIn("income was not recorded", detail)
        page = self.client.get(
            reverse("households:household_detail", args=[prediction.household.pk])
        ).content.decode()
        self.assertIn("estimated income", page)

    def test_recorded_income_is_not_flagged(self):
        prediction = self.score(make())
        self.assertFalse(prediction.income_was_estimated)
        detail = self.client.get(reverse("predictions:detail", args=[prediction.pk])).content.decode()
        self.assertNotIn("income was not recorded", detail)
