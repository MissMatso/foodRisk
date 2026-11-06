"""Ward and village spellings stay consistent, so one place is never counted as several."""

import importlib

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household

PASSWORD = "pw12345!"
COUNTER = iter(range(10_000))


def make(ward="Hantam", village="Calvinia", **overrides):
    number = next(COUNTER)
    values = dict(
        name=f"Family {number}",
        address=f"{number} Main Rd",
        contact=f"07{number:08d}"[:10],
        ward=ward,
        village=village,
        monthly_income=900,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )
    values.update(overrides)
    return Household.objects.create(**values)


class SpellingTests(TestCase):
    def test_a_new_entry_adopts_the_spelling_already_in_use(self):
        make("Hantam")
        for typed in ("hantam", "HANTAM", "  hantam  ", "Hantam."):
            self.assertEqual(make(typed).ward, "Hantam", typed)

    def test_the_most_common_existing_spelling_wins(self):
        make("Hantam")
        make("Hantam")
        stray = make("Hantam")
        Household.objects.filter(pk=stray.pk).update(ward="hantam")  # a legacy variant
        self.assertEqual(make("HANTAM").ward, "Hantam")

    def test_a_genuinely_new_place_keeps_its_own_capitals_and_loses_extra_spaces(self):
        self.assertEqual(make("  ZF   Mgcawu ").ward, "ZF Mgcawu")
        self.assertEqual(make("Pixley ka Seme").ward, "Pixley ka Seme")

    def test_villages_are_matched_within_their_own_ward(self):
        make("Hantam", "Calvinia")
        self.assertEqual(make("Hantam", "calvinia").village, "Calvinia")
        self.assertEqual(make("Namaqua", "calvinia").village, "calvinia")  # a different ward's village

    def test_blank_places_stay_blank(self):
        household = make("", "")
        self.assertEqual((household.ward, household.village), ("", ""))

    def test_the_analyst_filter_offers_one_option_per_place(self):
        make("Hantam")
        make("hantam")
        make("HANTAM ")
        CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")
        self.client.login(username="analyst1", password=PASSWORD)
        page = self.client.get(reverse("dashboard:risk_reports"))
        self.assertEqual(list(page.context["wards"]), ["Hantam"])


class SuggestionTests(TestCase):
    def test_the_form_suggests_existing_places(self):
        make("Hantam", "Calvinia")
        make("Namaqua", "Springbok")
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        self.client.login(username="staff1", password=PASSWORD)
        html = self.client.get(reverse("households:household_create")).content.decode()
        for place in ("Hantam", "Namaqua", "Calvinia", "Springbok"):
            self.assertIn(f'<option value="{place}">', html)
        self.assertIn('list="ward-options"', html)


class BackfillTests(TestCase):
    def test_existing_variants_are_merged_into_the_most_common_spelling(self):
        keep_a, keep_b, stray = make("Hantam"), make("Hantam"), make("Hantam")
        Household.objects.filter(pk=stray.pk).update(ward=" hantam", village="CALVINIA")
        importlib.import_module("households.migrations.0006_contact_address_keys_and_places").backfill(
            apps, None
        )
        for household in (keep_a, keep_b, stray):
            household.refresh_from_db()
            self.assertEqual((household.ward, household.village), ("Hantam", "Calvinia"))
