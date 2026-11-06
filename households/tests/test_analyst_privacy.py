"""Analysts work with scores and trends. They do not need a household's address or phone number."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import Household

PASSWORD = "pw12345!"


class AnalystPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for role in ("staff", "analyst", "admin"):
            CustomUser.objects.create_user(username=role, password=PASSWORD, role=role)
        cls.household = Household.objects.create(
            name="Private Family",
            address="12 Secret Lane",
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
        )

    def page(self, role):
        self.client.login(username=role, password=PASSWORD)
        url = reverse("households:household_detail", args=[self.household.pk])
        return self.client.get(url).content.decode()

    def test_the_analyst_page_hides_address_and_contact_but_keeps_what_analysis_needs(self):
        html = self.page("analyst")
        self.assertNotIn("12 Secret Lane", html)
        self.assertNotIn("071 111 2222", html)
        self.assertIn("not shown to analysts", html)
        self.assertIn("Private Family", html)
        self.assertIn("Hantam", html)

    def test_staff_and_admin_still_see_everything(self):
        for role in ("staff", "admin"):
            html = self.page(role)
            self.assertIn("12 Secret Lane", html, role)
            self.assertIn("071 111 2222", html, role)

    def test_the_api_withholds_address_and_contact_from_analysts(self):
        self.client.login(username="analyst", password=PASSWORD)
        detail = self.client.get(reverse("api-households-detail", args=[self.household.pk])).json()
        listing = self.client.get(reverse("api-households-list")).json()
        rows = listing["results"] if isinstance(listing, dict) else listing
        for payload in (detail, rows[0]):
            self.assertNotIn("address", payload)
            self.assertNotIn("contact", payload)
            self.assertEqual(payload["name"], "Private Family")

    def test_the_api_still_gives_staff_the_full_record(self):
        self.client.login(username="staff", password=PASSWORD)
        detail = self.client.get(reverse("api-households-detail", args=[self.household.pk])).json()
        self.assertEqual((detail["address"], detail["contact"]), ("12 Secret Lane", "071 111 2222"))
