"""Record a named review; activation is still a separate environment change."""

import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from accounts.models import CustomUser
from ml_engine.registry import digest, resolve_bundle, version_directory


class Command(BaseCommand):
    help = "Record an immutable review approval. Only trusted server operators should run this command."

    def add_arguments(self, parser):
        parser.add_argument("--model-version", required=True)
        parser.add_argument("--reviewer", required=True)
        parser.add_argument("--scope", choices=["research", "operational"], required=True)
        parser.add_argument("--evidence", required=True, help="Path to the signed-off review document")
        parser.add_argument("--notes", required=True)

    def handle(self, *args, **options):
        try:
            reviewer = CustomUser.objects.get(username=options["reviewer"], is_active=True)
            if not (reviewer.is_superuser or reviewer.role == "admin"):
                raise ValueError("Reviewer must be an active administrator")
            _, manifest = resolve_bundle(options["model_version"], serving=False)
            if options["scope"] == "operational" and not (
                manifest["validation"].get("ngo_external_validation")
                and manifest["validation"].get("rubric_targets_met")
            ):
                raise ValueError(
                    (
                        "Operational approval requires recorded external NGO validation and metric "
                        "gates; this research candidate is not eligible"
                    )
                )
            directory = version_directory(options["model_version"])
            approval = {
                "reviewer": reviewer.username,
                "scope": options["scope"],
                "reviewed_at": timezone.now().isoformat(),
                "manifest_sha256": digest(directory / "manifest.json"),
                "evidence_sha256": digest(Path(options["evidence"])),
                "notes": options["notes"],
            }
            with (directory / "approval.json").open("x", encoding="utf-8") as handle:
                json.dump(approval, handle, indent=2)
            self.stdout.write("Review recorded. No configuration or model activation was changed.")
        except (CustomUser.DoesNotExist, ValueError, OSError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
