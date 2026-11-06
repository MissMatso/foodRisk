"""The analyst CSV must not let a household name run as a spreadsheet formula."""

import csv
import io

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction
from households.testing import unique_address

PASSWORD = "pw12345!"


def make(name, ward="Hantam", contact="071 111 2222"):
    household = Household.objects.create(
        name=name,
        address=unique_address(),
        contact=contact,
        ward=ward,
        village="Calvinia",
        monthly_income=900,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )
    Prediction.objects.create(household=household, score=80, category="High", model_version="test")


class SafeCsvTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")

    def rows(self):
        self.client.login(username="analyst1", password=PASSWORD)
        body = self.client.get(reverse("dashboard:risk_export_csv")).content.decode()
        return list(csv.reader(io.StringIO(body)))[1:]

    def test_formula_like_names_and_wards_are_neutralised(self):
        make('=HYPERLINK("http://evil.example","click")', ward="@SUM(1+1)", contact="071 111 0001")
        make("+1+1", contact="071 111 0002")
        make("-2+3", contact="071 111 0003")
        cells = [cell for row in self.rows() for cell in (row[0], row[5])]
        for cell in cells:
            self.assertFalse(cell.startswith(("=", "+", "-", "@")), cell)
        self.assertIn("'=HYPERLINK", " ".join(cells))

    def test_ordinary_names_are_unchanged(self):
        make("Dlamini Household")
        self.assertEqual(self.rows()[0][0], "Dlamini Household")
