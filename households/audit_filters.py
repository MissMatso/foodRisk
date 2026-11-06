"""Filters shared by the household audit log and the account event log.

Both pages, and their CSV downloads, read the same validated values, so a
download always contains exactly the rows the page shows.
"""

from django import forms

from accounts.models import AccountEvent, CustomUser
from .models import AuditLog


class _PeriodForm(forms.Form):
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    user = forms.ModelChoiceField(
        queryset=CustomUser.objects.order_by("username"),
        required=False,
        empty_label="Anyone",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_from"] > data["date_to"]:
            raise forms.ValidationError("The start date must be on or before the end date.")
        return data

    def filter_period(self, queryset, field="timestamp"):
        data = self.cleaned_data
        if data.get("date_from"):
            queryset = queryset.filter(**{f"{field}__date__gte": data["date_from"]})
        if data.get("date_to"):
            queryset = queryset.filter(**{f"{field}__date__lte": data["date_to"]})
        return queryset


class HouseholdAuditFilterForm(_PeriodForm):
    action = forms.ChoiceField(
        choices=[("", "All actions")] + AuditLog.ACTION_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    household = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Household name"}),
    )

    def apply(self, logs):
        data = self.cleaned_data
        if data.get("action"):
            logs = logs.filter(action=data["action"])
        if data.get("user"):
            logs = logs.filter(changed_by=data["user"])
        if data.get("household"):
            logs = logs.filter(household_name__icontains=data["household"].strip())
        return self.filter_period(logs)


class AccountEventFilterForm(_PeriodForm):
    event_type = forms.ChoiceField(
        choices=[("", "All events")] + AccountEvent.EVENT_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].label = "Account"

    def apply(self, events):
        data = self.cleaned_data
        if data.get("event_type"):
            events = events.filter(event_type=data["event_type"])
        if data.get("user"):
            events = events.filter(user=data["user"])
        return self.filter_period(events)
