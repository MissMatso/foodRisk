from django.db import migrations
import encrypted_model_fields.fields


def protect_existing_records(apps, schema_editor):
    Household = apps.get_model("households", "Household")
    AuditLog = apps.get_model("households", "AuditLog")
    db = schema_editor.connection.alias

    # Copy through the encrypted field descriptor before dropping the old
    # plaintext column. AlterField alone would leave old values unencrypted.
    for household in Household.objects.using(db).all().iterator(chunk_size=500):
        Household.objects.using(db).filter(pk=household.pk).update(
            contact_encrypted=household.contact
        )

    # Historical audit diffs may contain names, addresses, contacts, income,
    # or health data. Keep the changed field names and remove all values.
    for log in AuditLog.objects.using(db).all().iterator(chunk_size=500):
        changes = log.changes
        if not isinstance(changes, dict) or changes.get("created") or changes.get("deleted"):
            continue
        fields = changes.get("fields_changed")
        if fields is None:
            fields = list(changes)
        AuditLog.objects.using(db).filter(pk=log.pk).update(
            changes={"fields_changed": fields}
        )


class Migration(migrations.Migration):
    dependencies = [("households", "0002_alter_household_has_chronic_illness_and_more")]

    operations = [
        migrations.AddField(
            model_name="household",
            name="contact_encrypted",
            field=encrypted_model_fields.fields.EncryptedCharField(
                max_length=20, null=True, blank=True
            ),
        ),
        # Old audit values are deliberately discarded; this data migration
        # cannot reconstruct them during a rollback.
        migrations.RunPython(protect_existing_records),
        migrations.RemoveField(model_name="household", name="contact"),
        migrations.RenameField(
            model_name="household", old_name="contact_encrypted", new_name="contact"
        ),
        migrations.AlterField(
            model_name="household",
            name="contact",
            field=encrypted_model_fields.fields.EncryptedCharField(max_length=20),
        ),
    ]
