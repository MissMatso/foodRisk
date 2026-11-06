"""Role separation, export safety and administrator report aggregates."""

import csv
import io
from datetime import datetime, date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from households.models import Household
from predictions.models import Prediction, Intervention
from .admin_reports import build_admin_report
from households.testing import unique_address


class AdminReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="administrator", role="admin")
        cls.staff = CustomUser.objects.create_user(username="worker", role="staff")
        cls.analyst = CustomUser.objects.create_user(username="analyst", role="analyst")
        cls.inactive = CustomUser.objects.create_user(username="disabled", role="staff", is_active=False)
        before = timezone.make_aware(datetime(2026, 9, 1, 10))
        inside = timezone.make_aware(datetime(2026, 10, 15, 10))
        CustomUser.objects.update(date_joined=before)
        CustomUser.objects.filter(pk=cls.inactive.pk).update(date_joined=inside)
        for i in range(2):
            hh = Household.objects.create(
                name=f"Private household {i}",
                address=unique_address("Private address"),
                contact="0000000000",
                monthly_income=2000,
                household_size=3,
                num_dependents=1,
                employment_status="unemployed",
                registered_by=cls.staff,
            )
            Household.objects.filter(pk=hh.pk).update(created_at=inside)
        for _ in range(3):
            pred = Prediction.objects.create(
                household=hh, score=75, category="High", model_version="test", generated_by=cls.staff
            )
            Prediction.objects.filter(pk=pred.pk).update(created_at=inside)
        action = Intervention.objects.create(
            prediction=pred, action="monitor", created_by=cls.staff, follow_up_date=date(2026, 10, 1)
        )
        Intervention.objects.filter(pk=action.pk).update(created_at=inside)
        pred = Prediction.objects.create(
            household=hh, score=20, category="Low", model_version="old", generated_by=None
        )
        Prediction.objects.filter(pk=pred.pk).update(created_at=before)

    def test_admin_default_and_legacy_downloads_choose_system_report(self):
        self.client.force_login(self.admin)
        for source, target in [
            ("reports", "admin_report"),
            ("export_csv", "admin_export_csv"),
            ("export_pdf", "admin_export_pdf"),
        ]:
            response = self.client.get(
                reverse("dashboard:" + source), {"date_from": "2026-10-01", "date_to": "2026-10-31"}
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("dashboard:" + target)))
            self.assertIn("date_from=2026-10-01", response.url)

    def test_analyst_retains_risk_reports_and_staff_is_denied(self):
        self.client.force_login(self.analyst)
        self.assertContains(self.client.get(reverse("dashboard:reports")), "Food-risk reports")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("dashboard:reports")).status_code, 403)

    def test_all_admin_routes_reject_non_admin_roles(self):
        for user in (self.staff, self.analyst):
            self.client.force_login(user)
            for name in ("admin_report", "admin_export_csv", "admin_export_pdf"):
                self.assertEqual(self.client.get(reverse("dashboard:" + name)).status_code, 403)

    def test_guest_and_deactivated_admin_cannot_download(self):
        self.assertEqual(self.client.get(reverse("dashboard:admin_export_csv")).status_code, 302)
        self.admin.is_active = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("dashboard:admin_export_pdf")).status_code, 302)

    def test_superuser_with_staff_role_can_view_system_report(self):
        self.staff.is_superuser = True
        self.staff.save()
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("dashboard:admin_report")), "System administration")

    def test_counts_are_not_multiplied_and_dates_are_inclusive(self):
        report = build_admin_report(date(2026, 10, 15), date(2026, 10, 15))
        self.assertEqual((report["total_users"], report["active_users"], report["inactive_users"]), (4, 3, 1))
        self.assertEqual(report["new_users"], 1)
        self.assertEqual(report["prediction_count"], 4)
        self.assertEqual(
            (report["period_households"], report["period_predictions"], report["period_interventions"]),
            (2, 3, 1),
        )
        row = next(r for r in report["accounts"] if r["username"] == "worker")
        self.assertEqual((row["households"], row["predictions"], row["interventions"]), (2, 3, 1))
        self.assertEqual(sum(r["total"] for r in report["roles"]), 4)

    def test_invalid_dates_reject_page_and_exports(self):
        self.client.force_login(self.admin)
        for params in ({"date_from": "nonsense"}, {"date_from": "2026-11-01", "date_to": "2026-10-01"}):
            for name in ("admin_report", "admin_export_csv", "admin_export_pdf"):
                self.assertEqual(self.client.get(reverse("dashboard:" + name), params).status_code, 400)

    def test_html_and_csv_agree_without_household_details(self):
        self.client.force_login(self.admin)
        params = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
        page = self.client.get(reverse("dashboard:admin_report"), params)
        self.assertEqual(page.context["report"]["period_predictions"], 3)
        self.assertNotContains(page, "Private household")
        response = self.client.get(reverse("dashboard:admin_export_csv"), params)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertIn(["Total users", "4"], rows)
        self.assertIn(["Assessments generated", "3"], rows)
        self.assertIn("system_admin_report.csv", response["Content-Disposition"])
        self.assertNotIn("Private address", response.content.decode())

    def test_pdf_and_csv_formula_safety(self):
        CustomUser.objects.create_user(username="=2+2", role="staff")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard:admin_export_csv"))
        self.assertIn("'=2+2", response.content.decode())
        response = self.client.get(reverse("dashboard:admin_export_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("system_admin_report.pdf", response["Content-Disposition"])

    def test_admin_can_open_separate_risk_analysis(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dashboard:risk_reports")), "Food-risk reports")
        self.assertIn(
            "predictions_report.csv",
            self.client.get(reverse("dashboard:risk_export_csv"))["Content-Disposition"],
        )

    def test_empty_period_still_reports_current_accounts(self):
        report = build_admin_report(date(2000, 1, 1), date(2000, 1, 2))
        self.assertEqual(report["total_users"], 4)
        self.assertEqual(report["period_predictions"], 0)
        self.assertEqual(report["new_users"], 0)
