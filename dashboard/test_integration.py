"""Security panel, account controls, risk filters, filtered exports, model card and the demo seed."""

import csv
import io
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountEvent, CustomUser
from households.models import AuditLog, Household
from predictions.models import Prediction

from .admin_reports import FAILED_LOGIN_ALERT, build_admin_report
from .model_card import build_model_card
from households.testing import unique_address

PASSWORD = "pw12345!"
MODEL = settings.FOODRISK_MODEL_VERSION


def make_household(name, ward, **overrides):
    values = dict(
        name=name,
        address=unique_address("Private Street"),
        contact="0123456789",
        ward=ward,
        village="Testville",
        monthly_income=2000,
        household_size=4,
        num_dependents=2,
        employment_status="unemployed",
    )
    values.update(overrides)
    return Household.objects.create(**values)


def make_prediction(household, category="High", score=80, version=MODEL):
    return Prediction.objects.create(
        household=household, category=category, score=score, model_version=version
    )


def add_event(event_type, username="", user=None, ago=None, ip="203.0.113.9"):
    event = AccountEvent.objects.create(event_type=event_type, username=username, user=user, ip_address=ip)
    if ago:
        AccountEvent.objects.filter(pk=event.pk).update(timestamp=timezone.now() - ago)
    return event


class AdminSecurityPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin1", password=PASSWORD, role="admin")
        cls.staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        cls.boss = CustomUser.objects.create_user(
            username="boss", password=PASSWORD, role="staff", is_superuser=True, is_staff=True
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def today_report(self):
        today = timezone.localdate()
        return build_admin_report(today, today)

    def test_period_counts_cover_each_event_type_and_exclude_other_days(self):
        add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff)
        add_event(AccountEvent.LOGIN_FAILED, "", None)  # no matching account
        add_event(AccountEvent.ROLE_CHANGED, "staff1", self.staff)
        add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff, ago=timedelta(days=10))
        report = self.today_report()
        self.assertEqual((report["login_failed_count"], report["login_failed_unknown_count"]), (2, 1))
        self.assertEqual(report["role_change_count"], 1)
        # force_login in setUp recorded one successful login for the admin
        self.assertEqual(report["login_success_count"], 1)

    def test_repeated_failures_warn_for_known_accounts_in_last_24_hours_only(self):
        for _ in range(FAILED_LOGIN_ALERT):
            add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff)
        for _ in range(FAILED_LOGIN_ALERT):
            add_event(AccountEvent.LOGIN_FAILED, "boss", self.boss, ago=timedelta(days=3))
        response = self.client.get(reverse("dashboard:admin_report"))
        self.assertEqual(
            response.context["report"]["repeated_failures"],
            [{"username": "staff1", "total": FAILED_LOGIN_ALERT}],
        )
        self.assertContains(response, "Possible password guessing")

    def test_no_warning_below_the_limit(self):
        for _ in range(FAILED_LOGIN_ALERT - 1):
            add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff)
        self.assertNotContains(
            self.client.get(reverse("dashboard:admin_report")), "Possible password guessing"
        )

    def test_unknown_name_failures_never_create_a_warning(self):
        for _ in range(FAILED_LOGIN_ALERT + 2):
            add_event(AccountEvent.LOGIN_FAILED, "", None)
        self.assertEqual(self.today_report()["repeated_failures"], [])

    def test_the_report_only_links_to_the_users_page_for_account_changes(self):
        response = self.client.get(reverse("dashboard:admin_report"))
        self.assertContains(response, reverse("accounts:user_list"))
        for user in (self.staff, self.boss):
            self.assertNotContains(response, reverse("accounts:user_role", args=[user.pk]))
            self.assertNotContains(response, reverse("accounts:user_status", args=[user.pk]))

    def test_account_controls_on_the_users_page_are_hidden_for_self_and_superusers(self):
        response = self.client.get(reverse("accounts:user_list"))
        can_manage = {u.username: u.can_manage for u in response.context["users"]}
        self.assertEqual(can_manage, {"admin1": False, "boss": False, "staff1": True})
        self.assertContains(response, reverse("accounts:user_role", args=[self.staff.pk]))
        self.assertNotContains(response, reverse("accounts:user_role", args=[self.boss.pk]))

    def test_a_role_change_on_the_users_page_shows_in_the_report(self):
        self.client.post(reverse("accounts:user_role", args=[self.staff.pk]), {"role": "analyst"})
        report_url = reverse("dashboard:admin_report") + "?date_from=2026-01-01&date_to=2099-01-01"
        response = self.client.get(report_url)
        self.assertContains(response, "Role changed")
        self.assertContains(response, "staff -&gt; analyst")

    def test_downloads_include_counts_but_no_network_addresses(self):
        add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff, ip="203.0.113.77")
        html = self.client.get(reverse("dashboard:admin_report")).content.decode()
        self.assertIn("203.0.113.77", html)  # visible to the admin on screen
        body = self.client.get(reverse("dashboard:admin_export_csv")).content.decode("utf-8-sig")
        self.assertNotIn("203.0.113.77", body)
        rows = list(csv.reader(io.StringIO(body)))
        self.assertIn(["Failed logins", "1"], rows)
        pdf = self.client.get(reverse("dashboard:admin_export_pdf"))
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertNotIn(b"203.0.113.77", pdf.content)

    def test_html_and_csv_agree_on_security_counts(self):
        add_event(AccountEvent.LOGIN_FAILED, "staff1", self.staff)
        page = self.client.get(reverse("dashboard:admin_report")).context["report"]
        rows = list(
            csv.reader(
                io.StringIO(
                    self.client.get(reverse("dashboard:admin_export_csv")).content.decode("utf-8-sig")
                )
            )
        )
        self.assertIn(["Failed logins", str(page["login_failed_count"])], rows)
        self.assertIn(["Successful logins", str(page["login_success_count"])], rows)


class RiskFilterAndExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")
        cls.hantam = make_household("Hantam Family", "Hantam")
        cls.namaqua = make_household("Namaqua Family", "Namaqua")
        make_prediction(cls.hantam)
        old = make_prediction(cls.namaqua, "Low", 10)
        Prediction.objects.filter(pk=old.pk).update(created_at="2026-01-15T10:00:00Z")

    def setUp(self):
        self.client.force_login(self.analyst)

    def csv_body(self, query=""):
        return self.client.get(reverse("dashboard:risk_export_csv") + query).content.decode()

    def test_page_counts_follow_the_ward_and_date_filters(self):
        url = reverse("dashboard:risk_reports")
        self.assertEqual(self.client.get(url).context["prediction_count"], 2)
        self.assertEqual(self.client.get(url, {"ward": "Hantam"}).context["prediction_count"], 1)
        january = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
        self.assertEqual(self.client.get(url, january).context["prediction_count"], 1)

    def test_csv_has_a_ward_column_and_respects_filters(self):
        self.assertIn("Household,Score,Category,Model Version,Generated At,Ward", self.csv_body())
        hantam = self.csv_body("?ward=Hantam")
        self.assertIn("Hantam Family", hantam)
        self.assertNotIn("Namaqua Family", hantam)
        january = self.csv_body("?date_from=2026-01-01&date_to=2026-01-31")
        self.assertIn("Namaqua Family", january)
        self.assertNotIn("Hantam Family", january)

    def test_bad_filters_are_rejected_everywhere(self):
        for params in ("?date_from=nonsense", "?date_from=2026-11-01&date_to=2026-10-01"):
            for name in ("risk_reports", "risk_export_csv", "risk_export_pdf"):
                response = self.client.get(reverse("dashboard:" + name) + params)
                self.assertEqual(response.status_code, 400, (name, params))

    def test_pdf_works_with_awkward_ward_text(self):
        for query in ("", "?ward=Hantam", "?ward=Tom+%26+Jerry+%3Cb%3E"):
            response = self.client.get(reverse("dashboard:risk_export_pdf") + query)
            self.assertEqual(response.status_code, 200, query)
            self.assertTrue(response.content.startswith(b"%PDF"))

    def test_the_download_form_carries_the_filters(self):
        page = self.client.get(
            reverse("dashboard:risk_reports"), {"ward": "Hantam", "date_from": "2026-01-01"}
        )
        self.assertContains(page, '<input type="hidden" name="ward" value="Hantam">', html=True)
        self.assertContains(page, '<input type="hidden" name="date_from" value="2026-01-01">', html=True)
        self.assertContains(page, reverse("dashboard:risk_export_csv"))
        self.assertContains(page, reverse("dashboard:risk_export_pdf"))
        self.assertNotContains(self.client.get(reverse("dashboard:risk_reports")), "(filtered)")

    def test_staff_still_cannot_use_the_risk_exports(self):
        staff = CustomUser.objects.create_user(username="staff1", password=PASSWORD, role="staff")
        self.client.force_login(staff)
        for name in ("risk_reports", "risk_export_csv", "risk_export_pdf"):
            self.assertEqual(self.client.get(reverse("dashboard:" + name)).status_code, 403)


class ModelCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.analyst = CustomUser.objects.create_user(username="analyst1", password=PASSWORD, role="analyst")

    def test_card_reads_the_active_manifest(self):
        card = build_model_card()
        self.assertEqual(card["version"], MODEL)
        matrix = card["matrix"]
        self.assertEqual(sum(matrix.values()), card["test_rows"])
        tiles = {tile["label"]: tile for tile in card["tiles"]}
        self.assertIsNone(tiles["Accuracy"]["target_percent"])
        for label in ("Precision", "Recall", "F1 score", "ROC AUC"):
            self.assertIsNotNone(tiles[label]["meets_target"], label)
        self.assertEqual([row["label"][:6] for row in card["baselines"]], ["Always", "Logist", "Random"])

    def test_card_is_none_for_unknown_or_broken_manifests(self):
        self.assertIsNone(build_model_card("no_such_model"))
        with patch("dashboard.model_card.json.loads", return_value={"comparisons": {}}):
            self.assertIsNone(build_model_card())

    def test_page_shows_card_with_honest_limits(self):
        self.client.force_login(self.analyst)
        page = self.client.get(reverse("dashboard:risk_reports"))
        self.assertContains(page, "Model performance")
        self.assertContains(page, "Confusion matrix")
        self.assertContains(page, "not externally validated")

    def test_page_renders_when_card_is_unavailable(self):
        self.client.force_login(self.analyst)
        with patch("dashboard.views.build_model_card", return_value=None):
            self.assertEqual(self.client.get(reverse("dashboard:risk_reports")).status_code, 200)


# The registry only serves an unapproved research model when DEBUG is on, as in local demos.
@override_settings(DEBUG=True)
class SeedCommandTests(TestCase):
    def run_seed(self, *args):
        call_command("seed_demo_data", *args, stdout=io.StringIO())

    def test_generated_households_come_only_from_held_out_rows(self):
        from households.management.commands.seed_demo_data import Command
        from ml_engine.train_simulated import load_dataframe, split_data

        splits = split_data(load_dataframe())
        used = {row["household_id"] for row in Command().heldout_rows()}
        self.assertEqual(len(used), len(splits["test"]))
        self.assertFalse(used & set(splits["train"].household_id))
        self.assertFalse(used & set(splits["validation"].household_id))

    def test_seed_builds_history_audit_and_login_activity(self):
        self.run_seed("--count", "12")
        generated = Household.objects.filter(name__contains=" #")
        self.assertEqual(generated.count(), 12)
        self.assertTrue(Prediction.objects.filter(household__in=generated, model_version=MODEL).exists())
        self.assertTrue(AuditLog.objects.filter(changed_by__username__startswith="staff_demo").exists())
        self.assertTrue(CustomUser.objects.get(username="analyst_demo").last_login)

    def test_seed_is_repeatable_and_reset_works(self):
        burst = {
            "detail__contains": "Demo data",
            "username": "admin_demo",
            "event_type": AccountEvent.LOGIN_FAILED,
        }
        self.run_seed("--count", "6")
        self.run_seed("--count", "6")
        self.assertEqual(Household.objects.filter(name__contains=" #").count(), 6)
        self.assertEqual(AccountEvent.objects.filter(**burst).count(), 6)
        self.run_seed("--reset", "--count", "0")
        self.assertFalse(Household.objects.filter(name__contains=" #").exists())
        self.assertEqual(Household.objects.count(), 5)
        self.assertEqual(AccountEvent.objects.filter(**burst).count(), 6)  # recreated once, not doubled
