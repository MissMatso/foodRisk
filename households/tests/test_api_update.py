"""Updating a household through the API (this used to fail for every valid update)."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import AuditLog, Household
from households.testing import unique_address

PASSWORD = "pw12345!"

BASE = dict(
    address="1 Main Rd",
    ward="Hantam",
    village="Calvinia",
    monthly_income=900,
    household_size=4,
    num_dependents=2,
    employment_status="unemployed",
)


class ApiUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.household = Household.objects.create(
            name="Update Me", contact="071 111 2222", **{**BASE, "address": unique_address()}
        )
        cls.other = Household.objects.create(
            name="Someone Else", contact="083 999 0000", **{**BASE, "address": unique_address()}
        )

    def setUp(self):
        self.client.login(username="staff1", password=PASSWORD)
        self.url = reverse("api-households-detail", args=[self.household.pk])

    def patch(self, body, url=None):
        return self.client.patch(url or self.url, data=body, content_type="application/json")

    def test_a_valid_partial_update_is_saved_and_audited(self):
        response = self.patch({"household_size": 5})
        self.assertEqual(response.status_code, 200, response.json())
        self.household.refresh_from_db()
        self.assertEqual(self.household.household_size, 5)
        self.assertEqual(AuditLog.objects.filter(household=self.household, action="update").count(), 1)

    def test_renaming_updates_the_duplicate_key(self):
        before = Household.objects.get(pk=self.household.pk).identity_key
        self.assertEqual(self.patch({"name": "Renamed Household"}).status_code, 200)
        self.assertNotEqual(Household.objects.get(pk=self.household.pk).identity_key, before)

    def test_a_full_update_works(self):
        payload = {
            **BASE,
            "name": "Update Me",
            "contact": "071 111 2222",
            "household_size": 6,
            "water_access": "piped",
        }
        response = self.client.put(self.url, data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.json())

    def test_an_update_into_another_households_identity_is_refused(self):
        response = self.patch({"name": "Someone Else", "contact": "083 999 0000"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("already registered", str(response.json()))
        self.household.refresh_from_db()
        self.assertEqual(self.household.name, "Update Me")

    def test_an_invalid_update_is_still_refused(self):
        self.assertEqual(self.patch({"contact": "n/a"}).status_code, 400)
        self.assertEqual(self.patch({"household_size": 0}).status_code, 400)
        self.household.refresh_from_db()
        self.assertEqual(self.household.household_size, 4)
