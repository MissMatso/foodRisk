"""Self-service password change, and automatic sign-out after inactivity."""

from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountEvent, CustomUser

OLD, NEW = "OldPassw0rd!x", "A-new-long-passphrase-42"


class PasswordChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(username="staff1", password=OLD, role="staff")

    def setUp(self):
        self.client.login(username="staff1", password=OLD)
        self.url = reverse("accounts:password_change")

    def change(self, old=OLD, new=NEW):
        return self.client.post(self.url, {"old_password": old, "new_password1": new, "new_password2": new})

    def test_anonymous_users_are_sent_to_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_a_user_can_change_their_own_password_and_stays_signed_in(self):
        response = self.change()
        self.assertRedirects(response, reverse("accounts:password_change_done"))
        self.assertEqual(self.client.get(reverse("accounts:password_change_done")).status_code, 200)
        self.client.logout()
        self.assertFalse(self.client.login(username="staff1", password=OLD))
        self.assertTrue(self.client.login(username="staff1", password=NEW))

    def test_the_change_is_recorded_without_the_password(self):
        self.change()
        event = AccountEvent.objects.get(event_type=AccountEvent.PASSWORD_CHANGED)
        self.assertEqual((event.user, event.performed_by), (self.user, self.user))
        self.assertNotIn(NEW, f"{event.username}{event.detail}")

    def test_the_wrong_current_password_changes_nothing(self):
        response = self.change(old="not-my-password")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_weak_passwords_are_rejected(self):
        for weak in ("password123", "short1!", "12345678901234"):
            self.assertEqual(self.change(new=weak).status_code, 200, weak)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_every_role_can_reach_the_link_from_the_menu(self):
        for role in ("staff", "analyst", "admin"):
            user = CustomUser.objects.create_user(username=f"u_{role}", password=OLD, role=role)
            self.client.force_login(user)
            html = self.client.get(reverse("how_it_works")).content.decode() if role == "x" else None
            page = (
                reverse("dashboard:admin_report") if role == "admin" else reverse("dashboard:risk_dashboard")
            )
            html = self.client.get(page).content.decode()
            self.assertIn(self.url, html, role)


class SessionTimeoutTests(TestCase):
    def test_sessions_expire_after_inactivity_and_slide_with_activity(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, settings.SESSION_IDLE_MINUTES * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_an_expired_session_is_sent_back_to_sign_in(self):
        user = CustomUser.objects.create_user(username="staff1", password=OLD, role="staff")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard:risk_dashboard")).status_code, 200)
        Session.objects.update(expire_date=timezone.now() - timedelta(minutes=1))
        response = self.client.get(reverse("dashboard:risk_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
