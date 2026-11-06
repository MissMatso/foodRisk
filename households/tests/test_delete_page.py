"""Deleting a household from the web interface (BR-12): System Admin only, confirmed, audited."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from households.models import AuditLog, Household
from households.testing import unique_address
from predictions.models import Prediction

PASSWORD = "pw12345!"


class HouseholdDeletePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user("admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        cls.analyst = CustomUser.objects.create_user("analyst1", password=PASSWORD, role="analyst")

    def setUp(self):
        self.household = Household.objects.create(
            name="Erase Me",
            address=unique_address(),
            contact="071 111 2222",
            ward="Hantam",
            village="Calvinia",
            monthly_income=900,
            household_size=4,
            num_dependents=0,
            employment_status="unemployed",
        )
        Prediction.objects.create(household=self.household, score=80, category="High", model_version="x")
        self.url = reverse("households:household_delete", args=[self.household.pk])

    def test_only_a_system_admin_sees_the_button(self):
        detail = reverse("households:household_detail", args=[self.household.pk])
        for user, visible in ((self.admin, True), (self.staff, False), (self.analyst, False)):
            self.client.force_login(user)
            page = self.client.get(detail)
            (self.assertContains if visible else self.assertNotContains)(page, self.url)

    def test_staff_and_analysts_cannot_delete(self):
        for user in (self.staff, self.analyst):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())

    def test_the_confirmation_page_says_what_will_be_lost_and_deletes_nothing(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.url)
        self.assertContains(page, "1 risk assessment")
        self.assertContains(page, "cannot be undone")
        self.assertTrue(Household.objects.filter(pk=self.household.pk).exists())

    def test_admin_deletes_and_lands_on_the_audit_entry(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, follow=True)
        self.assertFalse(Household.objects.filter(pk=self.household.pk).exists())
        self.assertFalse(Prediction.objects.filter(household_id=self.household.pk).exists())
        entry = AuditLog.objects.get(action=AuditLog.ACTION_DELETE, household_name="Erase Me")
        self.assertEqual(entry.changed_by, self.admin)
        self.assertContains(response, "were deleted")
        self.assertEqual([log.pk for log in response.context["logs"]], [entry.pk])


class NavigationTests(TestCase):
    def test_django_admin_is_not_in_the_menu(self):
        admin = CustomUser.objects.create_user(
            "boss", password=PASSWORD, role="admin", is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)
        page = self.client.get(reverse("accounts:user_list"))
        self.assertNotContains(page, 'href="/admin/"')
