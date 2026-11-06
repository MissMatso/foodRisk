"""Deleting a household also deletes its whole assessment history, so it is a System Admin action."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import AuditLog, Household
from predictions.models import Prediction

PASSWORD = "pw12345!"


class DeletionPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")

    def setUp(self):
        self.household = Household.objects.create(
            name="Delete Me",
            address="1 Main Rd",
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=2,
            employment_status="unemployed",
        )
        Prediction.objects.create(household=self.household, score=80, category="High", model_version="test")
        self.url = reverse("api-households-detail", args=[self.household.pk])

    def delete_as(self, username):
        if username:
            self.client.login(username=username, password=PASSWORD)
        return self.client.delete(self.url)

    def test_staff_cannot_delete_a_household(self):
        response = self.delete_as("staff1")
        self.assertEqual(response.status_code, 403)
        self.assertIn("System Admin", str(response.data))
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())
        self.assertEqual(Prediction.objects.count(), 1)

    def test_analysts_and_anonymous_users_cannot_delete(self):
        self.assertEqual(self.delete_as(None).status_code, 403)
        self.assertEqual(self.delete_as("analyst1").status_code, 403)
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())

    def test_a_system_admin_can_delete_and_the_deletion_is_recorded(self):
        response = self.delete_as("admin1")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Household.objects.filter(pk=self.household.pk).exists())
        self.assertEqual(Prediction.objects.count(), 0)  # the history goes with the household
        entry = AuditLog.objects.get(action=AuditLog.ACTION_DELETE)
        self.assertEqual((entry.household_name, entry.changed_by), ("Delete Me", self.admin))

    def test_staff_can_still_update_a_household(self):
        self.client.login(username="staff1", password=PASSWORD)
        response = self.client.patch(self.url, data={"household_size": 5}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
