"""Django management command wrapper around ml_engine/train_model.py so the
model can be retrained with `python manage.py train_model`."""

from django.core.management.base import BaseCommand

from ml_engine import train_model, train_simulated


class Command(BaseCommand):
    help = (
        "Retrains the Random Forest on the original simulated CSV by default as " "a new immutable candidate."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dataset", choices=("simulated", "ghs2024"), default="simulated")
        parser.add_argument(
            "--model-version", help="Unique candidate version; existing versions cannot be overwritten"
        )

    def handle(self, *args, **options):
        trainer = train_simulated if options["dataset"] == "simulated" else train_model
        passed = trainer.main(version=options["model_version"])
        if passed:
            self.stdout.write(self.style.SUCCESS("\nHeld-out metric thresholds met for this dataset only."))
        else:
            self.stdout.write(self.style.WARNING("\nSome metric thresholds were NOT met — see output above."))
