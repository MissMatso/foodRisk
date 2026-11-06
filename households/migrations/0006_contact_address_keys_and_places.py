from collections import Counter, defaultdict

from django.db import migrations, models

from households.identity import address_key, contact_key, normalise_text
from households.locations import tidy


def backfill(apps, schema_editor):
    """Give existing households their contact and address keys, and merge spelling variants of
    wards and villages ("hantam " and "Hantam") into the most common spelling."""
    Household = apps.get_model("households", "Household")
    households = list(Household.objects.order_by("pk").iterator())

    ward_spellings = defaultdict(Counter)
    village_spellings = defaultdict(Counter)
    for household in households:
        ward_spellings[normalise_text(household.ward)][tidy(household.ward)] += 1
        village_spellings[(normalise_text(household.ward), normalise_text(household.village))][
            tidy(household.village)
        ] += 1

    for household in households:
        ward = tidy(household.ward)
        village = tidy(household.village)
        if ward:
            ward = ward_spellings[normalise_text(household.ward)].most_common(1)[0][0]
        if village:
            village = village_spellings[(normalise_text(household.ward), normalise_text(household.village))].most_common(
                1
            )[0][0]
        Household.objects.filter(pk=household.pk).update(
            ward=ward,
            village=village,
            contact_key=contact_key(household.contact),
            address_key=address_key(household.address, village),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("households", "0005_household_identity_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="household",
            name="contact_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="household",
            name="address_key",
            field=models.CharField(blank=True, db_index=True, editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
