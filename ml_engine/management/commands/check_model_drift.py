"""Manual aggregate drift screen for a recent, de-identified mapped-input CSV."""

import json
from pathlib import Path
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from ml_engine.monitoring import compare_profile
from ml_engine.registry import resolve_bundle


class Command(BaseCommand):
    help = "Screen already mapped model inputs for drift (no automatic retraining)."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True)
        parser.add_argument("--model-version")
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            _, manifest = resolve_bundle(options["model_version"], serving=False)
            feature_cols = manifest["features"]
            df = pd.read_csv(options["csv"], dtype={"province": str, "water_access": str})
            if not set(feature_cols).issubset(df):
                raise ValueError("CSV must contain all mapped feature columns; see docs/MODEL_GOVERNANCE.md")
            report = compare_profile(df[feature_cols], manifest["drift_reference"])
            report["model_version"] = manifest["model_version"]
            # Exclusive create preserves prior monitoring evidence.
            with Path(options["output"]).open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
            self.stdout.write(report["status"])
        except (ValueError, OSError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
