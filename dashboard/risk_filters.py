"""Ward, category and date filters for the food-risk report and its CSV/PDF exports.

The page and both downloads read the same validated values, so a filtered
download is always built from the same rules as the page. Bad input is
rejected (HTTP 400) rather than silently ignored.
"""

from urllib.parse import urlencode

from django import forms


class RiskFilterForm(forms.Form):
    ward = forms.CharField(required=False, max_length=100)
    category = forms.ChoiceField(
        required=False,
        choices=[("", "All categories"), ("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError("Start date must be on or before end date.")
        return data


def apply_risk_filters(predictions, data):
    """Narrow a Prediction queryset by the validated filter values."""
    if data.get("ward"):
        predictions = predictions.filter(household__ward=data["ward"])
    if data.get("category"):
        predictions = predictions.filter(category=data["category"])
    if data.get("date_from"):
        predictions = predictions.filter(created_at__date__gte=data["date_from"])
    if data.get("date_to"):
        predictions = predictions.filter(created_at__date__lte=data["date_to"])
    return predictions


def filter_query(data):
    """URL query string for the export buttons ('' when no filter is set)."""
    chosen = {}
    for key in ("ward", "category", "date_from", "date_to"):
        value = data.get(key)
        if value:
            chosen[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return urlencode(chosen)


def describe_filters(data):
    """One readable line for the PDF header."""
    parts = [f"Ward: {data['ward']}" if data.get("ward") else "All wards"]
    if data.get("category"):
        parts.append(f"Category: {data['category']}")
    if data.get("date_from"):
        parts.append(f"From: {data['date_from'].isoformat()}")
    if data.get("date_to"):
        parts.append(f"To: {data['date_to'].isoformat()}")
    return "; ".join(parts)
