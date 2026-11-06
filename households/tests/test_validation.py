"""Household validation tests — FR003."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from households.models import Household


class HouseholdValidationTests(TestCase):
    def _build(self, **overrides):
        defaults = dict(
            name="Test Household",
            address="123 Main Street",
            contact="0123456789",
            monthly_income=Decimal("3500.00"),
            household_size=4,
            num_dependents=2,
            employment_status="employed",
        )
        defaults.update(overrides)
        return Household(**defaults)

    def test_valid_household_saves_successfully(self):
        household = self._build()
        household.save()
        self.assertIsNotNone(household.pk)

    def test_negative_income_is_rejected(self):
        household = self._build(monthly_income=Decimal("-1.00"))
        with self.assertRaises(ValidationError):
            household.save()

    def test_zero_household_size_is_rejected(self):
        household = self._build(household_size=0, num_dependents=0)
        with self.assertRaises(ValidationError):
            household.save()

    def test_dependents_exceeding_size_is_rejected(self):
        household = self._build(household_size=2, num_dependents=5)
        with self.assertRaises(ValidationError):
            household.save()

    def test_income_per_capita_property(self):
        household = self._build(monthly_income=Decimal("4000.00"), household_size=4)
        household.save()
        self.assertEqual(household.income_per_capita, 1000.0)

    def test_children_and_elderly_must_be_counted_as_dependents(self):
        household = self._build(children_under_5=2, elderly_members=1, num_dependents=2)
        with self.assertRaises(ValidationError):
            household.save()
