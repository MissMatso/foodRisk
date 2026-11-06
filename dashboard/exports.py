"""What an analyst downloads from the risk report: which rows and which columns.

The analyst picks the columns and the scope on the report page. The choices
arrive as ordinary GET parameters, are validated here, and the CSV and PDF
downloads are both built from the same validated choice, so they always agree.

Personal details (address, phone number) are never offered: analysts do not
see them anywhere in the system.
"""

from django import forms
from django.conf import settings
from django.db.models import OuterRef, Subquery

# key -> (column heading, how to read the value from a Prediction)
COLUMNS = {
    "household": ("Household", lambda p: p.household.name),
    "ward": ("Ward", lambda p: p.household.ward),
    "village": ("Village", lambda p: p.household.village),
    "employment": ("Employment", lambda p: p.household.get_employment_status_display()),
    "household_size": ("Household size", lambda p: p.household.household_size),
    "score": ("Score", lambda p: p.score),
    "category": ("Category", lambda p: p.category),
    "income_estimated": ("Income estimated", lambda p: "Yes" if p.income_was_estimated else "No"),
    "model_version": ("Model Version", lambda p: p.model_version),
    "generated_at": ("Generated At", lambda p: p.created_at),
}
# The original download, kept as the default so old links and bookmarks still work.
DEFAULT_COLUMNS = ["household", "score", "category", "model_version", "generated_at", "ward"]

SCOPE_LATEST = "latest"
SCOPE_ALL = "all"


class ExportOptionsForm(forms.Form):
    columns = forms.MultipleChoiceField(
        choices=[(key, heading) for key, (heading, _read) in COLUMNS.items()],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    scope = forms.ChoiceField(
        choices=[
            (SCOPE_ALL, "Every assessment (all model versions)"),
            (SCOPE_LATEST, "Latest assessment per household (current model only)"),
        ],
        required=False,
        widget=forms.RadioSelect,
    )

    def chosen_columns(self):
        """Columns in the order the analyst sees them on the page; the default set if none is ticked."""
        picked = set(self.cleaned_data.get("columns") or DEFAULT_COLUMNS)
        order = DEFAULT_COLUMNS if not self.cleaned_data.get("columns") else list(COLUMNS)
        return [key for key in order if key in picked]

    def chosen_scope(self):
        return self.cleaned_data.get("scope") or SCOPE_ALL


def latest_per_household(predictions):
    """Keep only each household's newest assessment from the current model."""
    current = predictions.filter(model_version=settings.FOODRISK_MODEL_VERSION)
    version = settings.FOODRISK_MODEL_VERSION
    newest = (
        current.model.objects.filter(household=OuterRef("household"), model_version=version)
        .order_by("-created_at", "-pk")
        .values("pk")[:1]
    )
    return current.filter(pk=Subquery(newest))


def export_rows(predictions, options):
    """(headings, rows) for the chosen columns and scope."""
    if options.chosen_scope() == SCOPE_LATEST:
        predictions = latest_per_household(predictions)
    columns = options.chosen_columns()
    headings = [COLUMNS[key][0] for key in columns]
    rows = [[COLUMNS[key][1](prediction) for key in columns] for prediction in predictions]
    return headings, rows


def describe_options(options):
    latest = options.chosen_scope() == SCOPE_LATEST
    scope = "latest assessment per household" if latest else "every assessment"
    return f"Rows: {scope}. Columns: " + ", ".join(COLUMNS[key][0] for key in options.chosen_columns())
