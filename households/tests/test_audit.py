"""Audit trail tests — create/update/delete on Household produce AuditLog
entries, matching the AuditLog entity in the Phase 2 ERD."""

from decimal import Decimal

from django.test import Client, TestCase
from django.db import connection

from accounts.models import CustomUser
from households.models import AuditLog, Household


class AuditTrailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(username="audit_staff", password="pw12345!", role="staff")

    def _build(self, **overrides):
        defaults = dict(
            name="Audit Household",
            address="1 Test Rd",
            contact="0110000000",
            monthly_income=Decimal("2500.00"),
            household_size=4,
            num_dependents=2,
            employment_status="employed",
        )
        defaults.update(overrides)
        return Household(**defaults)

    def test_direct_save_creates_audit_log_without_user(self):
        household = self._build()
        household.save()
        log = AuditLog.objects.get(household=household)
        self.assertEqual(log.action, AuditLog.ACTION_CREATE)
        self.assertIsNone(log.changed_by)

    def test_direct_update_logs_changed_fields(self):
        household = self._build()
        household.save()
        AuditLog.objects.filter(household=household).delete()

        household.monthly_income = Decimal("3000.00")
        household.save()

        log = AuditLog.objects.get(household=household, action=AuditLog.ACTION_UPDATE)
        self.assertEqual(log.changes, {"fields_changed": ["monthly_income"]})
        with connection.cursor() as cursor:
            cursor.execute("SELECT changes FROM households_auditlog WHERE id = %s", [log.pk])
            stored = cursor.fetchone()[0]
        self.assertNotIn("2500.00", stored)
        self.assertNotIn("3000.00", stored)

    def test_update_with_no_real_change_does_not_log(self):
        household = self._build()
        household.save()
        AuditLog.objects.filter(household=household).delete()

        household.save()  # re-save with identical values
        self.assertFalse(AuditLog.objects.filter(household=household, action=AuditLog.ACTION_UPDATE).exists())

    def test_delete_logs_with_null_household_fk(self):
        household = self._build()
        household.save()
        name = household.name
        household.delete()

        log = AuditLog.objects.get(household_name=name, action=AuditLog.ACTION_DELETE)
        self.assertIsNone(log.household)

    def test_web_edit_attributes_change_to_logged_in_user(self):
        household = self._build()
        household.save()

        client = Client()
        client.login(username="audit_staff", password="pw12345!")
        response = client.post(
            f"/households/{household.pk}/edit/",
            data={
                "name": household.name,
                "address": household.address,
                "contact": household.contact,
                "ward": "",
                "village": "",
                "province": "3",
                "monthly_income": "4200.00",
                "household_size": household.household_size,
                "num_dependents": household.num_dependents,
                "employment_status": household.employment_status,
                "has_disabled_member": "",
                "has_chronic_illness": "",
                "children_under_5": 0,
                "elderly_members": 0,
                "distance_to_market_km": 0,
                "water_access": "piped",
                "land_ownership": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        log = AuditLog.objects.filter(household=household, action=AuditLog.ACTION_UPDATE).latest("timestamp")
        self.assertEqual(log.changed_by.username, "audit_staff")
        self.assertIn("monthly_income", log.changes["fields_changed"])

    def test_contact_is_encrypted_in_database_and_changes_do_not_log_values(self):
        household = self._build()
        household.save()
        with connection.cursor() as cursor:
            cursor.execute("SELECT contact FROM households_household WHERE id = %s", [household.pk])
            stored = cursor.fetchone()[0]
        self.assertNotIn("0110000000", stored)
        self.assertEqual(Household.objects.get(pk=household.pk).contact, "0110000000")

        household.contact = "0821234567"
        household.address = "A new address"
        household.save()
        log = AuditLog.objects.get(household=household, action=AuditLog.ACTION_UPDATE)
        self.assertEqual(set(log.changes["fields_changed"]), {"contact", "address"})
        self.assertNotIn("0821234567", str(log.changes))
        self.assertNotIn("A new address", str(log.changes))
