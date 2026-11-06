"""The address is the main duplicate control.

A second household at the same address in the same village is refused unless
staff record why it is a separate household (for example a backyard room).
The rule lives in Household.clean(), so the web form and the API both apply it.
"""

import importlib

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household

PASSWORD = "pw12345!"

BASE = dict(
    name="Dlamini Household",
    address="12 Main Road",
    contact="071 111 2222",
    ward="Hantam",
    village="Calvinia",
    monthly_income=900,
    household_size=4,
    num_dependents=2,
    employment_status="unemployed",
)


def make(**overrides):
    return Household.objects.create(**{**BASE, **overrides})


def form_data(**overrides):
    return {
        **BASE,
        "province": "3",
        "water_access": "piped",
        "distance_to_market_km": 5,
        "children_under_5": 0,
        "elderly_members": 0,
        **overrides,
    }


class SharedAddressRuleTests(TestCase):
    def test_four_family_members_applying_separately_create_one_household(self):
        """Each applies under their own name and phone number, but they live at one address."""
        first = make(name="Thabo Dlamini", contact="071 000 0001")
        for number, name in enumerate(["Lerato Dlamini", "Sipho Dlamini", "Naledi Dlamini"], start=2):
            with self.assertRaises(ValidationError) as caught:
                make(name=name, contact=f"071 000 000{number}", address="12 main rd.")
            self.assertIn(f"record {first.pk}", caught.exception.message_dict["shared_address_reason"][0])
        self.assertEqual(Household.objects.count(), 1)

    def test_a_recorded_reason_allows_a_separate_household_at_the_same_address(self):
        make()
        backyard = make(
            name="Mokoena Family",
            contact="083 999 0000",
            shared_address_reason="  Backyard   room 2 ",
        )
        self.assertEqual(backyard.shared_address_reason, "Backyard room 2")  # spacing tidied

    def test_the_same_street_address_in_another_village_is_allowed(self):
        make()
        make(name="Mokoena Family", contact="083 999 0000", village="Williston")
        self.assertEqual(Household.objects.count(), 2)

    def test_placeholder_addresses_are_never_treated_as_shared(self):
        make(address="unknown")
        make(name="Mokoena Family", contact="083 999 0000", address="Unknown")
        self.assertEqual(Household.objects.count(), 2)

    def test_editing_a_household_does_not_clash_with_itself(self):
        household = make()
        household.monthly_income = 1200
        household.save()  # no error

    def test_moving_a_household_onto_an_occupied_address_needs_a_reason(self):
        make()
        other = make(name="Mokoena Family", contact="083 999 0000", address="5 Station Rd")
        other.address = "12 Main Road"
        with self.assertRaises(ValidationError):
            other.save()


class SharedAddressFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")

    def setUp(self):
        self.client.login(username="staff1", password=PASSWORD)
        self.existing = make()

    def test_the_form_shows_the_reason_box_and_refuses_without_a_reason(self):
        response = self.client.post(
            reverse("households:household_create"),
            form_data(name="Mokoena Family", contact="083 999 0000"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="shared_address_reason"')
        self.assertContains(response, "backyard room")
        self.assertContains(response, f"record {self.existing.pk}")
        self.assertNotContains(response, 'type="hidden" name="shared_address_reason"')
        self.assertEqual(Household.objects.count(), 1)

    def test_the_reason_box_is_hidden_when_the_address_is_free(self):
        response = self.client.get(reverse("households:household_create"))
        self.assertContains(response, 'type="hidden" name="shared_address_reason"')

    def test_the_form_saves_with_a_reason(self):
        response = self.client.post(
            reverse("households:household_create"),
            form_data(name="Mokoena Family", contact="083 999 0000", shared_address_reason="Flat B"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Household.objects.get(name="Mokoena Family").shared_address_reason, "Flat B")


class SharedAddressApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")

    def setUp(self):
        self.client.login(username="staff1", password=PASSWORD)
        make()

    def payload(self, **overrides):
        return {**form_data(name="Mokoena Family", contact="083 999 0000"), **overrides}

    def test_the_api_applies_the_same_rule(self):
        response = self.client.post(
            reverse("api-households-list"), self.payload(), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("shared_address_reason", response.json())

    def test_the_api_accepts_a_reason(self):
        response = self.client.post(
            reverse("api-households-list"),
            self.payload(shared_address_reason="Backyard room"),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)


class DatabaseCheckTests(TestCase):
    """The database refuses impossible numbers even when clean() is skipped (e.g. a bulk update)."""

    def test_impossible_numbers_are_refused_by_the_database(self):
        household = make()
        for change in (
            {"household_size": 0},
            {"num_dependents": 9},
            {"children_under_5": 3, "elderly_members": 3},
        ):
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():
                Household.objects.filter(pk=household.pk).update(**change)


class ExistingSharedAddressMigrationTests(TestCase):
    def test_existing_shared_addresses_get_a_placeholder_reason_instead_of_being_blocked(self):
        first = make()
        second = make(name="Mokoena Family", contact="083 999 0000", shared_address_reason="x")
        Household.objects.filter(pk=second.pk).update(shared_address_reason="")  # as before the rule
        migration = importlib.import_module("households.migrations.0007_shared_address_reason_and_checks")
        migration.mark_existing_shared_addresses(apps, None)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.shared_address_reason, "")
        self.assertEqual(second.shared_address_reason, migration.EXISTING_REASON)
