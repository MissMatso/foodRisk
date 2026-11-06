"""One family registering under different names: a shared phone number or address raises a warning."""

import importlib
import re

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.forms import HouseholdForm
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


class SharedPhoneOrAddressTests(TestCase):
    def reasons(self, **overrides):
        form = HouseholdForm(data=form_data(**overrides))
        form.is_valid()
        return [(h.pk, h.reasons) for h in form.possible_duplicates]

    def test_the_same_phone_number_under_another_name_needs_confirmation(self):
        existing = make()
        found = self.reasons(name="Mokoena Family", address="3 Other Street", contact="+27 71 111 2222")
        self.assertEqual(found, [(existing.pk, ["same phone number"])])

    def test_the_same_address_under_another_name_and_number_needs_confirmation(self):
        existing = make()
        found = self.reasons(name="Mokoena Family", address="12 main rd.", contact="083 999 0000")
        self.assertEqual(found, [(existing.pk, ["same address"])])

    def test_the_same_street_address_in_another_village_is_not_flagged(self):
        make()
        self.assertEqual(self.reasons(name="Mokoena Family", contact="083 999 0000", village="Williston"), [])

    def test_placeholder_addresses_never_match_each_other(self):
        make(address="n/a")
        for placeholder in ("N/A", "None", "unknown", "no address"):
            found = self.reasons(name="Other Family", address=placeholder, contact="083 999 0000")
            self.assertEqual(found, [], placeholder)

    def test_several_reasons_are_all_reported(self):
        existing = make()
        found = self.reasons(contact="083 999 0000", address="9 Elsewhere Lane")  # same name only
        self.assertEqual(found, [(existing.pk, ["same name"])])
        found = self.reasons(name="Mokoena Family")  # same phone number and same address
        self.assertEqual(found, [(existing.pk, ["same phone number", "same address"])])

    def test_the_same_name_and_phone_in_one_village_is_refused_not_warned(self):
        make()
        form = HouseholdForm(data=form_data(address="9 Elsewhere Lane"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.possible_duplicates, [])  # the hard rule answers this one
        self.assertIn("already registered", " ".join(form.non_field_errors()))

    def test_a_confirmed_household_is_saved_and_the_hard_rule_still_applies(self):
        make()
        confirmed = HouseholdForm(
            data=form_data(
                name="Mokoena Family", contact="071 111 2222", address="3 Other St", confirm_distinct="on"
            )
        )
        self.assertTrue(confirmed.is_valid(), confirmed.errors)
        confirmed.save()
        self.assertEqual(Household.objects.count(), 2)
        identical = HouseholdForm(data=form_data(confirm_distinct="on"))
        self.assertFalse(identical.is_valid())

    def test_editing_never_raises_the_warning(self):
        make()
        other = make(name="Mokoena Family", contact="083 999 0000", address="3 Other St")
        form = HouseholdForm(
            data=form_data(name="Mokoena Family", contact="071 111 2222", address="3 Other St"),
            instance=other,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_keys_are_hashes_and_are_never_sent_by_the_api(self):
        household = make()
        self.assertEqual(len(household.contact_key), 64)
        self.assertEqual(len(household.address_key), 64)
        self.assertNotIn("1112222", household.contact_key)
        self.assertEqual(
            make(name="Other", contact="+27711112222", address="x" * 8).contact_key, household.contact_key
        )
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        self.client.login(username="staff1", password=PASSWORD)
        payload = self.client.get(reverse("api-households-detail", args=[household.pk])).json()
        self.assertNotIn("contact_key", payload)
        self.assertNotIn("address_key", payload)


class WarningScreenTests(TestCase):
    def test_the_warning_names_the_match_without_revealing_its_number_or_address(self):
        existing = make()
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        self.client.login(username="staff1", password=PASSWORD)
        # Typed in another format, so what the form echoes back differs from what is stored.
        response = self.client.post(
            reverse("households:household_create"),
            form_data(name="Mokoena Family", address="3 Other St", contact="+27 71 111 2222"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Possible duplicate")
        self.assertContains(response, "same phone number")
        self.assertContains(response, reverse("households:household_detail", args=[existing.pk]))
        warning = re.search(
            r'<div class="alert alert-warning".*?</div>', response.content.decode(), re.S
        ).group(0)
        self.assertIn("Dlamini Household", warning)
        for private in ("071 111 2222", "0711112222", "12 Main Road"):
            self.assertNotIn(private, warning)


class BackfillTests(TestCase):
    def test_existing_households_get_their_keys(self):
        household = make()
        Household.objects.filter(pk=household.pk).update(contact_key=None, address_key=None)
        importlib.import_module("households.migrations.0006_contact_address_keys_and_places").backfill(
            apps, None
        )
        household.refresh_from_db()
        self.assertEqual((len(household.contact_key), len(household.address_key)), (64, 64))
