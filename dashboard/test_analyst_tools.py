"""Analyst tools: sortable dashboard, ward and employment breakdowns, and choosing what to download."""

import csv
import io

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from households.testing import unique_address
from predictions.models import Prediction

PASSWORD = "pw12345!"
MODEL = settings.FOODRISK_MODEL_VERSION


def make(name, ward, employment="unemployed", size=4):
    return Household.objects.create(
        name=name,
        address=unique_address(),
        contact="071 111 2222",
        ward=ward,
        village="Testville",
        monthly_income=900,
        household_size=size,
        num_dependents=0,
        employment_status=employment,
    )


def score(household, value, version=MODEL):
    category = "Low" if value <= 33 else "Medium" if value <= 66 else "High"
    return Prediction.objects.create(
        household=household, score=value, category=category, model_version=version
    )


class AnalystToolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.analyst = CustomUser.objects.create_user("analyst1", password=PASSWORD, role="analyst")
        cls.a = make("Aphane", "Hantam", "employed", size=2)
        cls.b = make("Botha", "Hantam", "unemployed", size=6)
        cls.c = make("Cele", "Namaqua", "unemployed", size=3)
        cls.unscored = make("Zulu", "Namaqua")
        score(cls.a, 20)
        score(cls.b, 50)
        score(cls.b, 80)  # Botha's newest score
        score(cls.c, 70)
        score(cls.c, 10, version="older_model")  # a different model never counts as "latest"

    def setUp(self):
        self.client.force_login(self.analyst)

    def dashboard_names(self, **params):
        response = self.client.get(reverse("dashboard:risk_dashboard"), params)
        self.assertEqual(response.status_code, 200)
        return [h.name for h in response.context["households"]]

    def test_dashboard_sorts_by_any_column_and_unscored_households_stay_last(self):
        self.assertEqual(
            self.dashboard_names(), ["Botha", "Cele", "Aphane", "Zulu"]
        )  # default: highest score
        self.assertEqual(self.dashboard_names(sort="score"), ["Aphane", "Cele", "Botha", "Zulu"])
        self.assertEqual(self.dashboard_names(sort="name"), ["Aphane", "Botha", "Cele", "Zulu"])
        self.assertEqual(self.dashboard_names(sort="-size"), ["Botha", "Zulu", "Cele", "Aphane"])

    def test_unknown_sort_keys_fall_back_to_the_default(self):
        self.assertEqual(self.dashboard_names(sort="address"), ["Botha", "Cele", "Aphane", "Zulu"])

    def test_dashboard_filters_by_ward_and_headings_keep_filters(self):
        self.assertEqual(self.dashboard_names(ward="Namaqua"), ["Cele", "Zulu"])
        page = self.client.get(reverse("dashboard:risk_dashboard"), {"ward": "Namaqua", "sort": "name"})
        self.assertContains(page, "?ward=Namaqua&amp;sort=-name")  # clicking again reverses
        self.assertContains(page, 'aria-sort="ascending"')

    def test_breakdowns_count_each_household_once_using_its_latest_score(self):
        context = self.client.get(reverse("dashboard:risk_reports")).context
        wards = {row["label"]: row for row in context["breakdowns"]["ward"]}
        self.assertEqual(wards["Hantam"]["households"], 2)
        self.assertEqual((wards["Hantam"]["high"], wards["Hantam"]["low"]), (1, 1))
        self.assertEqual(wards["Hantam"]["average"], 50.0)  # (20 + 80) / 2, the older 50 is ignored
        self.assertEqual(wards["Namaqua"]["households"], 1)  # Zulu has no score
        jobs = {row["label"]: row for row in context["breakdowns"]["employment"]}
        self.assertEqual(jobs["Unemployed"]["high_share"], 100.0)

    def test_category_filter_applies_to_the_report(self):
        context = self.client.get(reverse("dashboard:risk_reports"), {"category": "High"}).context
        self.assertEqual(context["prediction_count"], 2)

    def download(self, **params):
        response = self.client.get(reverse("dashboard:risk_export_csv"), params)
        self.assertEqual(response.status_code, 200)
        return list(csv.reader(io.StringIO(response.content.decode())))

    def test_the_analyst_chooses_the_columns(self):
        rows = self.download(columns=["household", "village", "score"])
        self.assertEqual(rows[0], ["Household", "Village", "Score"])
        self.assertEqual(len(rows), 1 + 5)  # every assessment by default

    def test_latest_only_gives_one_row_per_scored_household(self):
        rows = self.download(columns=["household", "score"], scope="latest")
        self.assertEqual(sorted(rows[1:]), [["Aphane", "20.0"], ["Botha", "80.0"], ["Cele", "70.0"]])

    def test_filters_and_choices_combine(self):
        rows = self.download(
            columns=["household", "category"], scope="latest", ward="Hantam", category="High"
        )
        self.assertEqual(rows, [["Household", "Category"], ["Botha", "High"]])

    def test_personal_details_cannot_be_requested(self):
        response = self.client.get(reverse("dashboard:risk_export_csv"), {"columns": ["address"]})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(reverse("dashboard:risk_export_pdf"), {"columns": ["contact"]})
        self.assertEqual(response.status_code, 400)

    def test_pdf_uses_the_chosen_columns(self):
        response = self.client.get(
            reverse("dashboard:risk_export_pdf"),
            {
                "columns": [
                    "household",
                    "ward",
                    "village",
                    "employment",
                    "household_size",
                    "score",
                    "category",
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
