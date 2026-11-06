from django.conf import settings
from django.core.management.base import BaseCommand

from ml_engine.global_explanation import write


class Command(BaseCommand):
    help = (
        "Compute the model-wide SHAP summary (mean |SHAP| per feature) on the model's held-out test records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model-version", default=None, help="Model version (default: the configured model)"
        )

    def handle(self, *args, **options):
        version = options["model_version"] or settings.FOODRISK_MODEL_VERSION
        path, summary = write(version)
        self.stdout.write(f"Baseline (average training score): {summary['baseline_probability']:.3f}")
        for name, value in summary["mean_absolute_shap"].items():
            self.stdout.write(f"  {name:<24} {value:.4f}")
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} from {summary['records']} test records."))
