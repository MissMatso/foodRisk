"""Phone number format and plausibility limits (catching typing slips)."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.forms import HouseholdForm
from households.models import MAX_DISTANCE_KM, MAX_HOUSEHOLD_SIZE, MAX_MONTHLY_INCOME, Household

PASSWORD = "pw12345!"

BASE = dict(
    name="Limits Household",
    address="1 Main Rd",
    contact="071 111 2222",
    ward="Hantam",
    village="Calvinia",
    monthly_income=900,
    household_size=4,
    num_dependents=2,
    employment_status="unemployed",
)


def errors_for(**overrides):
    """The field errors raised when saving a household with these values."""
    with_unique_name = {"name": f"H {abs(hash(str(overrides)))}"}
    try:
        Household.objects.create(**{**BASE, **with_unique_name, **overrides})
    except ValidationError as exc:
        return exc.message_dict
    return {}


class ContactTests(TestCase):
    def test_south_african_numbers_in_common_formats_are_accepted(self):
        for contact in ("071 111 2222", "0711112222", "+27 71 111 2222", "+27711112222", "(071) 111-2222"):
            self.assertNotIn("contact", errors_for(contact=contact), contact)

    def test_anything_else_is_rejected(self):
        for contact in ("n/a", "abcdef", "12345", "0711", "07111122223", "+44 7911 123456", "none"):
            self.assertIn("contact", errors_for(contact=contact), contact)

    def test_a_missing_number_cannot_be_used_to_dodge_the_duplicate_rule(self):
        # Without a valid number there is no identity key, so a number is now always required.
        for _ in range(2):
            self.assertIn("contact", errors_for(name="Same Name", contact="n/a"))
        self.assertEqual(Household.objects.count(), 0)


class PlausibilityLimitTests(TestCase):
    def test_values_at_the_limit_are_accepted_and_one_above_is_rejected(self):
        cases = [
            ("monthly_income", MAX_MONTHLY_INCOME, MAX_MONTHLY_INCOME + 1),
            ("household_size", MAX_HOUSEHOLD_SIZE, MAX_HOUSEHOLD_SIZE + 1),
            ("distance_to_market_km", MAX_DISTANCE_KM, MAX_DISTANCE_KM + 1),
        ]
        for field, ok, too_big in cases:
            self.assertNotIn(field, errors_for(**{field: ok}), field)
            self.assertIn(field, errors_for(**{field: too_big}), field)

    def test_the_messages_tell_the_user_what_to_check(self):
        self.assertIn("typing error", " ".join(errors_for(monthly_income=99_999_999)["monthly_income"]))
        self.assertIn("South African phone number", " ".join(errors_for(contact="n/a")["contact"]))


class FormAndApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")

    def test_the_web_form_shows_the_contact_message(self):
        data = {
            **BASE,
            "province": "3",
            "water_access": "piped",
            "distance_to_market_km": 5,
            "children_under_5": 0,
            "elderly_members": 0,
            "contact": "n/a",
        }
        form = HouseholdForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("contact", form.errors)

    def test_the_api_returns_400_for_a_bad_contact_or_size(self):
        self.client.login(username="staff1", password=PASSWORD)
        payload = {**BASE, "water_access": "piped", "contact": "n/a", "household_size": 500}
        response = self.client.post(reverse("api-households-list"), data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("contact", response.data)
        self.assertIn("household_size", response.data)
