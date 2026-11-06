"""What each role sees in the menu and where they land after signing in."""

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser

PASSWORD = "pw12345!"

DASHBOARD = 'href="/dashboard/"'
HOUSEHOLDS = 'href="/households/"'
REGISTER = 'href="/households/new/"'
USERS = 'href="/accounts/users/"'
AUDIT = 'href="/households/audit-log/"'


class MenuByRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")
        cls.boss = CustomUser.objects.create_user(
            username="boss", password=PASSWORD, role="staff", is_superuser=True, is_staff=True
        )

    def page(self, user, url_name):
        self.client.force_login(user)
        return self.client.get(reverse(url_name)).content.decode()

    def test_admin_menu_has_oversight_pages_only(self):
        html = self.page(self.admin, "dashboard:admin_report")
        for hidden in (DASHBOARD, HOUSEHOLDS, REGISTER):
            self.assertNotIn(hidden, html)
        for shown in (USERS, AUDIT, 'href="/dashboard/reports/"'):
            self.assertIn(shown, html)
        self.assertIn(">System report<", html)

    def test_superuser_with_staff_role_is_treated_as_system_admin(self):
        html = self.page(self.boss, "dashboard:admin_report")
        for hidden in (DASHBOARD, HOUSEHOLDS, REGISTER):
            self.assertNotIn(hidden, html)

    def test_staff_menu_is_unchanged(self):
        html = self.page(self.staff, "households:household_list")
        for shown in (DASHBOARD, HOUSEHOLDS, REGISTER):
            self.assertIn(shown, html)
        self.assertNotIn(USERS, html)

    def test_analyst_menu_is_unchanged(self):
        html = self.page(self.analyst, "dashboard:risk_dashboard")
        for shown in (DASHBOARD, HOUSEHOLDS, "Risk reports"):
            self.assertIn(shown, html)
        self.assertNotIn(REGISTER, html)
        self.assertNotIn(USERS, html)

    def test_hiding_the_links_does_not_change_permissions(self):
        # The menu is presentation only; the pages still enforce roles themselves.
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("dashboard:risk_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("households:household_create")).status_code, 200)
        self.client.force_login(self.analyst)
        self.assertEqual(self.client.get(reverse("households:household_create")).status_code, 403)

    def test_public_header_button_points_each_role_to_its_own_home(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn('href="/dashboard/reports/system/"', html)
        self.assertIn("Open system report", html)
        self.client.force_login(self.staff)
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("Open dashboard", html)
        self.assertNotIn("Open system report", html)


class LoginLandingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CustomUser.objects.create_user(username="admin1", password=PASSWORD, role="admin")
        CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")

    def sign_in(self, username, **extra):
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": PASSWORD, **extra}
        )

    def test_admin_lands_on_the_system_report(self):
        response = self.sign_in("admin1")
        self.assertRedirects(response, reverse("dashboard:admin_report"), fetch_redirect_response=False)

    def test_staff_and_analyst_still_land_on_the_dashboard(self):
        for username in ("staff1", "analyst1"):
            self.client.logout()
            response = self.sign_in(username)
            self.assertRedirects(response, reverse("dashboard:risk_dashboard"), fetch_redirect_response=False)

    def test_a_safe_next_address_is_still_honoured(self):
        response = self.sign_in("admin1", next=reverse("accounts:user_list"))
        self.assertRedirects(response, reverse("accounts:user_list"), fetch_redirect_response=False)

    def test_an_unsafe_next_address_is_ignored(self):
        response = self.sign_in("admin1", next="https://evil.example/")
        self.assertRedirects(response, reverse("dashboard:admin_report"), fetch_redirect_response=False)

    def test_visiting_the_sign_in_page_while_signed_in_says_who_is_signed_in(self):
        self.sign_in("admin1")
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You are already signed in")
        self.assertContains(response, "admin1")
        self.assertContains(response, reverse("dashboard:admin_report"))  # continue as this user
        self.assertContains(response, reverse("accounts:logout"))  # or sign out
        self.assertNotContains(response, 'name="password"')


class RegisterHouseholdEntryPointTests(TestCase):
    """Staff reach the registration form from the Households page only (no duplicate menu item)."""

    def test_menu_has_no_register_item_but_the_households_page_has_the_button(self):
        staff = CustomUser.objects.create_user("staff_nav", password="pw12345!", role="staff")
        self.client.force_login(staff)
        create = reverse("households:household_create")
        dashboard = self.client.get(reverse("dashboard:risk_dashboard")).content.decode()
        self.assertNotIn(f'href="{create}"', dashboard)
        households = self.client.get(reverse("households:household_list")).content.decode()
        self.assertEqual(households.count(f'href="{create}"'), 1)
        self.assertIn("before registering", households)


class ExpiredFormTests(TestCase):
    """A form whose security token went stale shows a plain explanation, not Django's technical page."""

    def test_stale_sign_in_form_gets_the_friendly_page(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("accounts:login"), {"username": "x", "password": "y"})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "This page expired", status_code=403)
        self.assertContains(response, "private window", status_code=403)
        self.assertNotContains(response, "CSRF_FAILURE_VIEW", status_code=403)
