from django.test import TestCase
from django.urls import reverse
from accounts.models import CustomUser


class UserStatusTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(username="manager", role="admin")
        self.staff = CustomUser.objects.create_user(username="worker", role="staff")
        self.url = reverse("accounts:user_status", args=[self.staff.pk])

    def test_admin_deactivates_and_reactivates(self):
        self.client.force_login(self.admin)
        for active in (False, True):
            self.assertEqual(self.client.post(self.url, {"active": str(int(active))}).status_code, 302)
            self.staff.refresh_from_db()
            self.assertEqual(self.staff.is_active, active)

    def test_staff_denied_and_get_is_read_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.url, {"active": "0"}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_self_and_superuser_protected(self):
        self.client.force_login(self.admin)
        root = CustomUser.objects.create_user(username="root", is_superuser=True)
        for target in (self.admin, root):
            self.client.post(reverse("accounts:user_status", args=[target.pk]), {"active": "0"})
            target.refresh_from_db()
            self.assertTrue(target.is_active)
