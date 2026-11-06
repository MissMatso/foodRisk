"""Role changes, deactivation and login tracking (accounts.AccountEvent)."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import AccountEvent, CustomUser

PASSWORD = "pw12345!"


class AccountActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")
        cls.boss = CustomUser.objects.create_user(
            username="boss", password=PASSWORD, role="staff", is_superuser=True, is_staff=True
        )

    def setUp(self):
        self.client.login(username="admin1", password=PASSWORD)

    def change_role(self, user, role, **extra):
        return self.client.post(reverse("accounts:user_role", args=[user.pk]), {"role": role, **extra})

    def test_admin_can_change_a_role_and_it_is_logged(self):
        response = self.change_role(self.staff, "analyst")
        self.assertRedirects(response, reverse("accounts:user_list"))
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, "analyst")
        event = AccountEvent.objects.get(event_type=AccountEvent.ROLE_CHANGED)
        self.assertEqual(
            (event.user, event.performed_by, event.detail), (self.staff, self.admin, "staff -> analyst")
        )

    def test_role_change_returns_to_the_report_when_asked(self):
        report_url = reverse("dashboard:admin_report") + "?date_from=2026-10-01&date_to=2026-10-31"
        response = self.change_role(self.staff, "analyst", next=report_url)
        self.assertRedirects(response, report_url, fetch_redirect_response=False)

    def test_external_next_url_is_ignored(self):
        response = self.change_role(self.staff, "analyst", next="https://evil.example/phish")
        self.assertRedirects(response, reverse("accounts:user_list"), fetch_redirect_response=False)

    def test_invalid_role_is_rejected(self):
        self.change_role(self.staff, "superhero")
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, "staff")
        self.assertFalse(AccountEvent.objects.filter(event_type=AccountEvent.ROLE_CHANGED).exists())

    def test_admin_cannot_change_own_role_or_a_superuser(self):
        self.change_role(self.admin, "staff")
        self.change_role(self.boss, "analyst")
        self.admin.refresh_from_db()
        self.boss.refresh_from_db()
        self.assertEqual((self.admin.role, self.boss.role), ("admin", "staff"))

    def test_non_admins_cannot_change_roles(self):
        for username in ("staff1", "analyst1"):
            self.client.login(username=username, password=PASSWORD)
            self.assertEqual(self.change_role(self.analyst, "admin").status_code, 403)
        self.analyst.refresh_from_db()
        self.assertEqual(self.analyst.role, "analyst")

    def test_role_view_needs_post(self):
        response = self.client.get(reverse("accounts:user_role", args=[self.staff.pk]))
        self.assertEqual(response.status_code, 405)

    def test_deactivate_and_reactivate_are_logged(self):
        url = reverse("accounts:user_status", args=[self.staff.pk])
        self.client.post(url, {"active": "0"})
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)
        self.client.post(url, {"active": "1"})
        types = AccountEvent.objects.filter(performed_by=self.admin).values_list("event_type", flat=True)
        self.assertCountEqual(types, [AccountEvent.ACCOUNT_DEACTIVATED, AccountEvent.ACCOUNT_ACTIVATED])


class LoginTrackingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")

    def failed(self):
        return AccountEvent.objects.filter(event_type=AccountEvent.LOGIN_FAILED)

    def test_failed_login_for_a_known_account_is_recorded_without_the_password(self):
        self.client.post(reverse("accounts:login"), {"username": "staff1", "password": "wrong-password-123"})
        event = self.failed().get()
        self.assertEqual((event.username, event.user, event.ip_address), ("staff1", self.staff, "127.0.0.1"))
        self.assertNotIn("wrong-password-123", f"{event.username}{event.detail}")

    def test_unknown_username_is_counted_but_its_text_is_not_stored(self):
        # People sometimes type a password into the username box.
        self.client.post(reverse("accounts:login"), {"username": "MyS3cretPassw0rd!", "password": "x"})
        event = self.failed().get()
        self.assertEqual((event.username, event.user, event.detail), ("", None, "Unknown username"))
        self.assertFalse(AccountEvent.objects.filter(username__contains="S3cret").exists())

    def test_deactivated_account_login_counts_as_failed(self):
        CustomUser.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.client.post(reverse("accounts:login"), {"username": "staff1", "password": PASSWORD})
        self.assertEqual(self.failed().get().user, self.staff)

    def test_successful_login_and_logout_are_recorded(self):
        self.client.post(reverse("accounts:login"), {"username": "staff1", "password": PASSWORD})
        self.assertTrue(
            AccountEvent.objects.filter(event_type=AccountEvent.LOGIN_SUCCESS, user=self.staff).exists()
        )
        self.client.post(reverse("accounts:logout"))
        self.assertTrue(AccountEvent.objects.filter(event_type=AccountEvent.LOGOUT, user=self.staff).exists())
