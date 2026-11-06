"""The audit log pages: filters, filter-keeping pagination, the account-event tab and CSV downloads."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountEvent, CustomUser
from households.models import AuditLog, Household
from households.testing import unique_address

PASSWORD = "pw12345!"


def make(name, user=None):
    household = Household.objects.create(
        name=name,
        address=unique_address(),
        contact="071 111 2222",
        ward="Hantam",
        village="Calvinia",
        monthly_income=900,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )
    AuditLog.objects.filter(household=household).update(changed_by=user)
    return household


class HouseholdAuditLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user("admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        cls.other = CustomUser.objects.create_user("staff2", password=PASSWORD, role="staff")
        cls.dlamini = make("Dlamini Household", cls.staff)
        cls.mokoena = make("Mokoena Family", cls.other)
        cls.mokoena.monthly_income = 1500
        cls.mokoena.save()
        old = AuditLog.objects.get(household=cls.dlamini)
        AuditLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(days=40))

    def setUp(self):
        self.client.force_login(self.admin)

    def names(self, **filters):
        response = self.client.get(reverse("households:audit_log"), filters)
        self.assertEqual(response.status_code, 200)
        return sorted((log.household_name, log.action) for log in response.context["logs"])

    def test_filter_by_action_user_household_and_date(self):
        self.assertEqual(self.names(action="update"), [("Mokoena Family", "update")])
        self.assertEqual(self.names(user=self.staff.pk), [("Dlamini Household", "create")])
        self.assertEqual(
            self.names(household="moko"), [("Mokoena Family", "create"), ("Mokoena Family", "update")]
        )
        recent = (timezone.localdate() - timedelta(days=7)).isoformat()
        self.assertEqual(len(self.names(date_from=recent)), 2)

    def test_bad_dates_are_refused_not_ignored(self):
        response = self.client.get(
            reverse("households:audit_log"), {"date_from": "2026-05-01", "date_to": "2026-04-01"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "start date must be on or before", status_code=400)

    def test_page_links_keep_the_filters(self):
        for number in range(55):
            make(f"Extra {number}", self.staff)
        response = self.client.get(reverse("households:audit_log"), {"action": "create"})
        self.assertContains(response, "?action=create&amp;page=2")
        second = self.client.get(reverse("households:audit_log"), {"action": "create", "page": 2})
        self.assertTrue(all(log.action == "create" for log in second.context["logs"]))

    def test_csv_download_matches_the_filters_and_has_no_values(self):
        response = self.client.get(reverse("households:audit_log_csv"), {"action": "update"})
        text = response.content.decode()
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("Mokoena Family", text)
        self.assertIn("monthly_income", text)
        self.assertNotIn("1500", text)
        self.assertNotIn("Dlamini", text)

    def test_the_page_explains_why_the_log_is_kept(self):
        self.assertContains(self.client.get(reverse("households:audit_log")), "Why these logs are kept")

    def test_only_administrators_see_the_logs(self):
        self.client.force_login(self.staff)
        for name in ("audit_log", "audit_log_csv", "account_events", "account_events_csv"):
            self.assertEqual(self.client.get(reverse(f"households:{name}")).status_code, 403, name)


class AccountEventLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user("admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user("staff1", password=PASSWORD, role="staff")
        AccountEvent.objects.create(
            event_type=AccountEvent.LOGIN_FAILED, username="staff1", user=cls.staff, ip_address="203.0.113.5"
        )
        AccountEvent.objects.create(
            event_type=AccountEvent.ROLE_CHANGED,
            username="staff1",
            user=cls.staff,
            performed_by=cls.admin,
            detail="staff -> analyst",
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_the_tab_lists_and_filters_account_events(self):
        response = self.client.get(
            reverse("households:account_events"), {"event_type": AccountEvent.ROLE_CHANGED}
        )
        self.assertEqual([e.detail for e in response.context["events"]], ["staff -> analyst"])
        everything = self.client.get(reverse("households:account_events"))
        self.assertContains(everything, "203.0.113.5")

    def test_the_download_leaves_out_network_addresses(self):
        text = self.client.get(reverse("households:account_events_csv")).content.decode()
        self.assertIn("Failed login", text)
        self.assertNotIn("203.0.113.5", text)
