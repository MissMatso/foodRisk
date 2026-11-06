from django.db import migrations, models

from households.identity import identity_key


def backfill_identity_keys(apps, schema_editor):
    """Give existing households their key. If two existing households are
    duplicates, only the oldest gets the key (the database allows one per key);
    list the rest with `python manage.py check_duplicate_households`."""
    Household = apps.get_model("households", "Household")
    seen = set()
    for household in Household.objects.order_by("pk").iterator():
        key = identity_key(household.name, household.ward, household.village, household.contact)
        if key and key not in seen:
            seen.add(key)
            Household.objects.filter(pk=household.pk).update(identity_key=key)


class Migration(migrations.Migration):

    dependencies = [
        ("households", "0004_household_province_alter_household_elderly_members_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="household",
            name="identity_key",
            field=models.CharField(blank=True, editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(backfill_identity_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="household",
            name="identity_key",
            field=models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True),
        ),
    ]
