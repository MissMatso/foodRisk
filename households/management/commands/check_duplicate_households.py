"""List households that look like duplicates. Prints record numbers and names only."""

from collections import defaultdict

from django.core.management.base import BaseCommand

from households.identity import identity_key, normalise_text
from households.models import Household


class Command(BaseCommand):
    help = "Lists possible duplicate households (record numbers and names only, no contact details)."

    def handle(self, *args, **options):
        keys = {}  # record number -> identity key
        same_identity = defaultdict(list)
        same_place_and_name = defaultdict(list)
        for household in Household.objects.order_by("pk"):
            key = identity_key(household.name, household.ward, household.village, household.contact)
            keys[household.pk] = key
            if key:
                same_identity[key].append(household)
            place = (
                normalise_text(household.name),
                normalise_text(household.ward),
                normalise_text(household.village),
            )
            same_place_and_name[place].append(household)

        found = False
        for group in same_identity.values():
            if len(group) > 1:
                found = True
                self.stdout.write(
                    self.style.ERROR(f"Same name, ward, village and contact: {self.describe(group)}")
                )
        for group in same_place_and_name.values():
            if len(group) > 1 and len({keys[h.pk] for h in group}) > 1:
                found = True
                self.stdout.write(
                    self.style.WARNING(
                        f"Same name in the same village, different contact: {self.describe(group)}"
                    )
                )
        if not found:
            self.stdout.write(self.style.SUCCESS("No duplicate or similar households found."))

    @staticmethod
    def describe(group):
        return f"records {', '.join(str(h.pk) for h in group)} ({group[0].name})"
