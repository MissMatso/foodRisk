"""Passwords chosen by an administrator must be replaced by the account owner."""

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AccountEvent, CustomUser
from dashboard.admin_reports import build_admin_report

ADMIN_PASSWORD = "AdminPassw0rd!zz"
TEMP = "Temp-Issued-Pass-9"
OWN = "My-Own-Long-Passphrase-31"


def flagged_user(username="newstaff", role="staff", password=TEMP):
    user = CustomUser.objects.create_user(username=username, password=password, role=role)
    CustomUser.objects.filter(pk=user.pk).update(must_change_password=True)
    user.refresh_from_db()
    return user


class FirstSignInTests(TestCase):
    def setUp(self):
        self.user = flagged_user()
        self.client.login(username="newstaff", password=TEMP)

    def test_every_page_sends_the_user_to_choose_their_own_password(self):
        for url in ("/dashboard/", "/households/", "/households/new/", "/"):
            response = self.client.get(url)
            self.assertRedirects(response, reverse("accounts:password_change"), fetch_redirect_response=False)

    def test_the_change_page_and_signing_out_stay_available(self):
        page = self.client.get(reverse("accounts:password_change"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "chosen by an administrator")
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)

    def test_the_api_refuses_with_a_clear_message(self):
        response = self.client.get("/api/households/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("choose your own password", response.json()["detail"])

    def test_choosing_a_new_password_clears_the_flag_and_unlocks_the_system(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": TEMP, "new_password1": OWN, "new_password2": OWN},
        )
        self.assertRedirects(response, reverse("accounts:password_change_done"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.assertNotContains(
            self.client.get(reverse("accounts:password_change")), "chosen by an administrator"
        )

    def test_the_new_password_cannot_be_the_temporary_one(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": TEMP, "new_password1": TEMP, "new_password2": TEMP},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must be different from your current password")
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_a_wrong_current_password_leaves_the_flag_in_place(self):
        self.client.post(
            reverse("accounts:password_change"),
            {"old_password": "wrong", "new_password1": OWN, "new_password2": OWN},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_users_who_chose_their_own_password_are_never_interrupted(self):
        CustomUser.objects.create_user(username="settled", password=OWN, role="staff")
        self.client.logout()
        self.client.login(username="settled", password=OWN)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)


class AdminIssuedAccountsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password=ADMIN_PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password=OWN, role="staff")
        cls.boss = CustomUser.objects.create_user(
            username="boss", password=OWN, role="staff", is_superuser=True, is_staff=True
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def reset(self, user):
        return self.client.post(reverse("accounts:user_password_reset", args=[user.pk]))

    def create_account(self, **overrides):
        data = {
            "username": "fresh",
            "email": "fresh@example.org",
            "first_name": "Fresh",
            "last_name": "Hire",
            "role": "staff",
            **overrides,
        }
        return self.client.post(reverse("accounts:register"), data)

    def test_new_accounts_get_a_generated_password_shown_once_with_the_username(self):
        response = self.create_account()
        self.assertEqual(
            response.status_code, 200, response.context.get("form") and response.context["form"].errors
        )
        temporary = response.context["temporary_password"]
        self.assertEqual(len(temporary), 12)
        self.assertContains(response, temporary)
        self.assertContains(response, "Account created for fresh")
        self.assertIn("no-store", response["Cache-Control"])
        fresh = CustomUser.objects.get(username="fresh")
        self.assertTrue(fresh.must_change_password)
        self.assertTrue(fresh.check_password(temporary))
        self.assertNotEqual(fresh.password, temporary)  # only the hash is stored

    def test_two_new_accounts_get_different_passwords(self):
        first = self.create_account().context["temporary_password"]
        second = self.create_account(username="fresh2").context["temporary_password"]
        self.assertNotEqual(first, second)

    def test_the_administrator_is_never_asked_to_type_a_password(self):
        page = self.client.get(reverse("accounts:register"))
        self.assertNotContains(page, 'type="password"')

    def test_account_creation_is_recorded_without_the_password(self):
        temporary = self.create_account(role="analyst").context["temporary_password"]
        event = AccountEvent.objects.get(event_type=AccountEvent.ACCOUNT_CREATED)
        self.assertEqual(
            (event.username, event.performed_by, event.detail), ("fresh", self.admin, "role analyst")
        )
        self.assertNotIn(temporary, f"{event.username}{event.detail}")

    def test_a_new_user_must_change_the_generated_password_before_using_the_system(self):
        temporary = self.create_account().context["temporary_password"]
        self.client.logout()
        self.assertTrue(self.client.login(username="fresh", password=temporary))
        response = self.client.get(reverse("dashboard:risk_dashboard"))
        self.assertRedirects(response, reverse("accounts:password_change"), fetch_redirect_response=False)

    def test_reset_shows_a_temporary_password_once_and_flags_the_account(self):
        response = self.reset(self.staff)
        self.assertEqual(response.status_code, 200)
        temporary = response.context["temporary_password"]
        self.assertEqual(len(temporary), 12)
        self.assertContains(response, temporary)
        self.assertIn("no-store", response["Cache-Control"])
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.must_change_password)
        self.assertTrue(self.staff.check_password(temporary))
        self.assertFalse(self.staff.check_password(OWN))

    def test_reset_is_recorded_without_the_password(self):
        temporary = self.reset(self.staff).context["temporary_password"]
        event = AccountEvent.objects.get(event_type=AccountEvent.PASSWORD_RESET)
        self.assertEqual((event.user, event.performed_by), (self.staff, self.admin))
        self.assertNotIn(temporary, f"{event.username}{event.detail}")

    def test_the_reset_account_is_signed_out_and_must_choose_a_password(self):
        other = self.client_class()
        other.login(username="staff1", password=OWN)
        self.assertEqual(other.get("/dashboard/").status_code, 200)
        temporary = self.reset(self.staff).context["temporary_password"]
        self.assertEqual(other.get("/dashboard/").status_code, 302)  # old session no longer valid
        other.login(username="staff1", password=temporary)
        self.assertRedirects(
            other.get("/dashboard/"), reverse("accounts:password_change"), fetch_redirect_response=False
        )

    def test_the_temporary_password_is_not_kept_in_the_flash_messages(self):
        temporary = self.reset(self.staff).context["temporary_password"]
        next_page = self.client.get(reverse("accounts:user_list"))
        self.assertNotContains(next_page, temporary)

    def test_reset_rules(self):
        self.assertEqual(
            self.client.get(reverse("accounts:user_password_reset", args=[self.staff.pk])).status_code, 405
        )
        self.reset(self.admin)  # own account
        self.reset(self.boss)  # a superuser, by a non-superuser
        for user in (self.admin, self.boss):
            user.refresh_from_db()
            self.assertFalse(user.must_change_password)
        self.assertFalse(AccountEvent.objects.filter(event_type=AccountEvent.PASSWORD_RESET).exists())

    def test_only_administrators_can_reset(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.reset(self.admin).status_code, 403)

    def test_the_system_report_counts_accounts_still_on_a_temporary_password(self):
        self.reset(self.staff)
        report = self.client.get(reverse("dashboard:admin_report")).context["report"]
        self.assertEqual(report["temporary_password_users"], 1)
        self.assertContains(
            self.client.get(reverse("dashboard:admin_report")), "Still on a temporary password: 1"
        )
        csv_body = self.client.get(reverse("dashboard:admin_export_csv")).content.decode("utf-8-sig")
        self.assertIn("Still on an administrator-issued password,1", csv_body)

    def test_the_report_helper_ignores_deactivated_accounts(self):
        self.reset(self.staff)
        CustomUser.objects.filter(pk=self.staff.pk).update(is_active=False)
        from django.utils import timezone

        today = timezone.localdate()
        self.assertEqual(build_admin_report(today, today)["temporary_password_users"], 0)


class DjangoAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = CustomUser.objects.create_user(
            username="boss", password=OWN, role="admin", is_superuser=True, is_staff=True
        )
        cls.staff = CustomUser.objects.create_user(username="staff1", password=OWN, role="staff")

    def setUp(self):
        self.client.force_login(self.boss)

    def change_password_in_admin(self, user):
        url = reverse("admin:auth_user_password_change", args=[user.pk])
        return self.client.post(url, {"password1": TEMP, "password2": TEMP})

    def test_a_password_set_for_someone_else_in_django_admin_is_flagged(self):
        response = self.change_password_in_admin(self.staff)
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.must_change_password)

    def test_changing_your_own_password_in_django_admin_is_not_flagged(self):
        self.change_password_in_admin(self.boss)
        self.boss.refresh_from_db()
        self.assertFalse(self.boss.must_change_password)


@override_settings(DEBUG=True)
class DemoAccountsTests(TestCase):
    def test_demo_accounts_are_not_flagged_so_the_demonstration_is_not_interrupted(self):
        from django.core.management import call_command
        import io

        call_command("seed_demo_data", "--count", "0", stdout=io.StringIO())
        self.assertFalse(
            CustomUser.objects.filter(username__endswith="_demo", must_change_password=True).exists()
        )
