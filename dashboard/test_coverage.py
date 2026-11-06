"""Response coverage on the analyst report: are high-risk households being reached?"""

from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser
from households.models import Household
from households.testing import unique_address
from predictions.models import Intervention, Prediction

PASSWORD = "pw12345!"
MODEL = settings.FOODRISK_MODEL_VERSION


def make(name, ward):
    return Household.objects.create(
        name=name,
        address=unique_address(),
        contact="071 111 2222",
        ward=ward,
        village="Testville",
        monthly_income=900,
        household_size=4,
        num_dependents=0,
        employment_status="unemployed",
    )


def score(household, value, version=MODEL):
    category = "Low" if value <= 33 else "Medium" if value <= 66 else "High"
    return Prediction.objects.create(
        household=household, score=value, category=category, model_version=version
    )


class ResponseCoverageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.analyst = CustomUser.objects.create_user("analyst1", password=PASSWORD, role="analyst")
        today = timezone.localdate()
        # Hantam: three High households - one reached, one with an overdue follow-up, one untouched.
        done = make("Done", "Hantam")
        old = score(done, 85)
        Intervention.objects.create(prediction=old, action="urgent_referral", status="completed")
        score(done, 90)  # rescored later: the earlier action still counts
        late = make("Late", "Hantam")
        Intervention.objects.create(
            prediction=score(late, 80), action="programme_referral", follow_up_date=today - timedelta(days=3)
        )
        make_untouched = make("Untouched", "Hantam")
        score(make_untouched, 75)
        # Namaqua: one Low household with an open follow-up in the future, one High under an old model only.
        low = make("Low", "Namaqua")
        Intervention.objects.create(
            prediction=score(low, 10), action="monitor", follow_up_date=today + timedelta(days=5)
        )
        score(make("Old model", "Namaqua"), 95, version="older_model")

    def setUp(self):
        self.client.force_login(self.analyst)

    def coverage(self, **filters):
        return self.client.get(reverse("dashboard:risk_reports"), filters).context["coverage"]

    def test_counts_each_household_once_and_keeps_earlier_actions(self):
        c = self.coverage()
        self.assertEqual((c["high"], c["high_reached"], c["not_reached"]), (3, 2, 1))
        self.assertEqual(c["reached_share"], 66.7)
        self.assertEqual((c["open"], c["overdue"]), (2, 1))

    def test_by_ward_lists_the_ward_with_most_unreached_first(self):
        rows = self.coverage()["by_ward"]
        self.assertEqual(rows[0]["ward"], "Hantam")
        self.assertEqual((rows[0]["high"], rows[0]["not_reached"], rows[0]["overdue"]), (3, 1, 1))
        namaqua = next(r for r in rows if r["ward"] == "Namaqua")
        self.assertEqual((namaqua["high"], namaqua["reached_share"], namaqua["open"]), (0, None, 1))

    def test_filters_apply(self):
        self.assertEqual(self.coverage(ward="Namaqua")["high"], 0)
        self.assertEqual(self.coverage(category="High")["high"], 3)

    def test_the_page_shows_the_panel_and_the_model_section_last(self):
        html = self.client.get(reverse("dashboard:risk_reports")).content.decode()
        self.assertIn("Response coverage", html)
        self.assertNotIn("Average effect in the explanations staff requested", html)
        self.assertLess(html.index('id="coverage"'), html.index('id="about-the-model"'))
        self.assertLess(html.index('id="download"'), html.index('id="about-the-model"'))
        self.assertNotIn("Untouched", html)  # counts only, never names
