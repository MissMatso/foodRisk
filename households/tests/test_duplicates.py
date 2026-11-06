"""Duplicate-household prevention: hard rule, soft rule, database rule, API and review tools."""

import importlib
import io
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.forms import HouseholdForm
from households.identity import identity_key, normalise_contact
from households.models import AuditLog, Household
from households.testing import unique_address

PASSWORD = "pw12345!"

BASE = dict(
    name="Dlamini Household",
    address="1 Main Rd",
    contact="071 111 2222",
    ward="Hantam",
    village="Calvinia",
    monthly_income="900.00",
    household_size=4,
    num_dependents=2,
    employment_status="unemployed",
)


def make(**overrides):
    return Household.objects.create(**{**BASE, "address": unique_address(), **overrides})


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


class HardRuleTests(TestCase):
    def test_identical_household_is_refused_and_names_the_existing_record(self):
        first = make()
        with self.assertRaises(ValidationError) as caught:
            make(address="Somewhere else entirely")  # address alone does not make it a new household
        message = " ".join(caught.exception.messages)
        self.assertIn("already registered", message)
        self.assertIn(f"record {first.pk}", message)
        self.assertEqual(Household.objects.count(), 1)

    def test_case_spacing_punctuation_and_phone_format_do_not_hide_a_duplicate(self):
        make()
        for variant in (
            dict(name="  dlamini   HOUSEHOLD "),
            dict(name="Dlamini Household."),
            dict(contact="+27 71 111 2222"),
            dict(contact="071-111-2222"),
            dict(ward="HANTAM", village="calvinia"),
        ):
            with self.assertRaises(ValidationError, msg=variant):
                make(**variant)

    def test_a_different_contact_ward_or_village_is_a_different_household(self):
        make()
        make(contact="083 999 0000")
        make(ward="Namaqua")
        make(village="Williston")
        self.assertEqual(Household.objects.count(), 4)

    def test_a_household_does_not_clash_with_itself_when_edited(self):
        household = make()
        household.household_size = 5
        household.save()
        self.assertEqual(Household.objects.count(), 1)

    def test_editing_into_another_households_identity_is_refused(self):
        make()
        other = make(contact="083 999 0000")
        other.contact = "071 111 2222"
        with self.assertRaises(ValidationError):
            other.save()

    def test_changing_a_contact_frees_the_old_identity(self):
        first = make()
        first.contact = "082 555 1212"
        first.save()
        make()  # the old name + contact combination is available again
        self.assertEqual(Household.objects.count(), 2)

    def test_key_is_a_keyed_hash_and_never_contains_the_contact(self):
        household = make()
        self.assertEqual(len(household.identity_key), 64)
        self.assertNotIn("1112222", household.identity_key)
        self.assertEqual(
            household.identity_key, identity_key("dlamini household", "hantam", "calvinia", "0711112222")
        )

    def test_phone_normalisation(self):
        self.assertEqual(normalise_contact("+27 71 111 2222"), "0711112222")
        self.assertEqual(normalise_contact("(071) 111-2222"), "0711112222")

    def test_audit_log_reports_the_name_change_not_the_derived_key(self):
        household = make()
        household.name = "Dlamini Family"
        household.save()
        entry = AuditLog.objects.filter(household=household, action=AuditLog.ACTION_UPDATE).first()
        self.assertEqual(entry.changes, {"fields_changed": ["name"]})


class DatabaseRuleTests(TestCase):
    def test_database_itself_refuses_two_households_with_one_key(self):
        first = make()
        second = make(contact="083 999 0000")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Household.objects.filter(pk=second.pk).update(identity_key=first.identity_key)

    def test_simultaneous_registration_is_turned_into_a_clear_error(self):
        make()
        # Simulate the second request passing the application check at the same moment.
        with patch.object(Household, "clean", lambda self: None):
            with self.assertRaises(ValidationError) as caught:
                make()
        self.assertIn("just been registered", " ".join(caught.exception.messages))
        self.assertEqual(Household.objects.count(), 1)


class SoftRuleFormTests(TestCase):
    def test_similar_household_needs_confirmation(self):
        existing = make()
        form = HouseholdForm(data=form_data(contact="083 999 0000"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.possible_duplicates, [existing])
        self.assertIn("confirm_distinct", form.errors)
        self.assertFalse(form["confirm_distinct"].is_hidden)  # the checkbox appears

        confirmed = HouseholdForm(data=form_data(contact="083 999 0000", confirm_distinct="on"))
        self.assertTrue(confirmed.is_valid(), confirmed.errors)
        confirmed.save()
        self.assertEqual(Household.objects.count(), 2)

    def test_an_identical_household_cannot_be_confirmed_away(self):
        make()
        form = HouseholdForm(data=form_data(confirm_distinct="on"))
        self.assertFalse(form.is_valid())
        self.assertIn("already registered", " ".join(form.non_field_errors()))

    def test_checkbox_is_hidden_until_needed_and_other_villages_are_not_flagged(self):
        make()
        fresh = HouseholdForm()
        self.assertTrue(fresh["confirm_distinct"].is_hidden)
        other_village = HouseholdForm(data=form_data(village="Williston", contact="083 999 0000"))
        self.assertTrue(other_village.is_valid(), other_village.errors)
        self.assertEqual(other_village.possible_duplicates, [])

    def test_editing_never_triggers_the_similar_household_warning(self):
        make()
        other = make(contact="083 999 0000", ward="Namaqua")
        data = form_data(contact="083 999 0000", ward="Hantam")
        form = HouseholdForm(data=data, instance=other)
        self.assertTrue(form.is_valid(), form.errors)


class RegistrationViewAndApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")

    def setUp(self):
        self.client.login(username="staff1", password=PASSWORD)
        self.url = reverse("households:household_create")

    def test_second_identical_registration_is_rejected_with_a_message(self):
        self.assertEqual(self.client.post(self.url, form_data()).status_code, 302)
        response = self.client.post(self.url, form_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already registered")
        self.assertEqual(Household.objects.count(), 1)

    def test_similar_household_shows_warning_with_link_then_saves_when_confirmed(self):
        existing = make()
        response = self.client.post(self.url, form_data(contact="083 999 0000"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Possible duplicate")
        self.assertContains(response, reverse("households:household_detail", args=[existing.pk]))
        self.assertNotContains(response, "1112222")  # no contact numbers on the warning
        response = self.client.post(self.url, form_data(contact="083 999 0000", confirm_distinct="on"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Household.objects.count(), 2)

    def test_fresh_form_has_no_visible_confirmation_box(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="confirm_distinct"', html)
        self.assertIn('type="hidden" name="confirm_distinct"', html)
        self.assertNotIn("Possible duplicate", html)

    def test_api_refuses_a_duplicate_and_never_exposes_the_key(self):
        payload = {
            "name": "API Household",
            "address": "4 Test Road",
            "contact": "0834567890",
            "ward": "Hantam",
            "village": "Calvinia",
            "monthly_income": "1500.00",
            "household_size": 4,
            "num_dependents": 2,
            "employment_status": "unemployed",
            "water_access": "piped",
        }
        first = self.client.post(reverse("api-households-list"), data=payload)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertNotIn("identity_key", first.data)
        second = self.client.post(reverse("api-households-list"), data=payload)
        self.assertEqual(second.status_code, 400)
        self.assertIn("already registered", str(second.data))
        self.assertEqual(Household.objects.count(), 1)


class ReviewToolsTests(TestCase):
    def make_legacy_duplicates(self):
        """Two households that were saved before this rule existed."""
        first = make()
        second = make(contact="083 999 0000")
        Household.objects.filter(pk=second.pk).update(contact="071 111 2222")  # bypasses the rule
        Household.objects.update(identity_key=None)
        return first, second

    def test_backfill_keys_the_oldest_and_leaves_later_duplicates_unkeyed(self):
        first, second = self.make_legacy_duplicates()
        migration = importlib.import_module("households.migrations.0005_household_identity_key")
        migration.backfill_identity_keys(apps, None)
        self.assertIsNotNone(Household.objects.get(pk=first.pk).identity_key)
        self.assertIsNone(Household.objects.get(pk=second.pk).identity_key)

    def test_review_command_lists_duplicates_without_personal_details(self):
        first, second = self.make_legacy_duplicates()
        out = io.StringIO()
        call_command("check_duplicate_households", stdout=out)
        text = out.getvalue()
        self.assertIn(f"records {first.pk}, {second.pk}", text)
        self.assertIn("Dlamini Household", text)
        self.assertNotIn("1112222", text)
        self.assertNotIn("Main Rd", text)

    def test_review_command_reports_similar_names_with_different_contacts(self):
        make()
        make(contact="083 999 0000")
        out = io.StringIO()
        call_command("check_duplicate_households", stdout=out)
        self.assertIn("different contact", out.getvalue())

    def test_review_command_on_clean_data(self):
        make()
        out = io.StringIO()
        call_command("check_duplicate_households", stdout=out)
        self.assertIn("No duplicate or similar households found", out.getvalue())
