from django import forms

from .identity import address_key, identity_key, similar_households
from .models import Household


class HouseholdForm(forms.ModelForm):
    """FR002 registration form with validation mirroring Household.clean() (FR003)."""

    confirm_distinct = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput,
        label="This is a different household from the similar one(s) listed above",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.possible_duplicates = []  # filled by clean() when a similar household exists
        # Let staff pick an existing spelling instead of inventing a new one.
        self.fields["ward"].widget.attrs.update({"list": "ward-options", "autocomplete": "off"})
        self.fields["village"].widget.attrs.update({"list": "village-options", "autocomplete": "off"})
        if self.instance.pk and self.instance.shared_address_reason:
            self.show_shared_address_reason()

    def show_shared_address_reason(self):
        """The reason box is only shown when the address is already in use (or already has a reason)."""
        self.fields["shared_address_reason"].widget = forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. backyard room 2, flat B"}
        )

    class Meta:
        model = Household
        fields = [
            "name",
            "address",
            "contact",
            "ward",
            "village",
            "province",
            "monthly_income",
            "household_size",
            "num_dependents",
            "employment_status",
            "has_disabled_member",
            "has_chronic_illness",
            "children_under_5",
            "elderly_members",
            "distance_to_market_km",
            "water_access",
            "land_ownership",
            "shared_address_reason",
        ]
        labels = {
            "name": "Household name (head of household)",
            "contact": "Phone number",
            "monthly_income": "Monthly household income (R)",
            "household_size": "Household size (people)",
            "num_dependents": "Number of dependents",
            "employment_status": "Main employment status",
            "has_disabled_member": "A household member has a disability",
            "has_chronic_illness": "A household member has a chronic illness",
            "children_under_5": "Children under 5",
            "distance_to_market_km": "Distance to the nearest market (km)",
            "water_access": "Main drinking-water source",
            "land_ownership": "The household owns land",
        }
        help_texts = {
            "province": "Recorded for case administration; not used by the active simulated-data model.",
            "num_dependents": (
                "Case-management total. The model uses children under five plus elderly members "
                "to match its training data."
            ),
        }
        widgets = {
            "province": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Household / head-of-household name",
                }
            ),
            "address": forms.TextInput(attrs={"class": "form-control", "placeholder": "Physical address"}),
            "contact": forms.TextInput(attrs={"class": "form-control", "placeholder": "0XX XXX XXXX"}),
            "ward": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. ZF Mgcawu"}),
            "village": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Upington"}),
            "monthly_income": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "household_size": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "num_dependents": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "employment_status": forms.Select(attrs={"class": "form-select"}),
            "has_disabled_member": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "has_chronic_illness": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "children_under_5": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "elderly_members": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "distance_to_market_km": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "water_access": forms.Select(attrs={"class": "form-select"}),
            "land_ownership": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "shared_address_reason": forms.HiddenInput,
        }

    def clean(self):
        cleaned_data = super().clean()
        income = cleaned_data.get("monthly_income")
        size = cleaned_data.get("household_size")
        dependents = cleaned_data.get("num_dependents")

        if income is not None and income < 0:
            self.add_error("monthly_income", "Income must be ≥ 0.")
        if size is not None and size <= 0:
            self.add_error("household_size", "Household size must be > 0.")
        if size is not None and dependents is not None and dependents > size:
            self.add_error("num_dependents", "Dependents cannot exceed household size.")
        place = address_key(cleaned_data.get("address"), cleaned_data.get("village"))
        if place and Household.objects.filter(address_key=place).exclude(pk=self.instance.pk).exists():
            self.show_shared_address_reason()  # the model's clean() says what is needed
        self.check_similar_households(cleaned_data)
        return cleaned_data

    def check_similar_households(self, data):
        """Soft rule: a similar household in the same village must be confirmed as different.

        Only when registering a new household. (An identical household is refused
        by the model itself and cannot be confirmed away.)
        """
        if self.instance.pk or data.get("confirm_distinct"):
            return
        key = identity_key(data.get("name"), data.get("ward"), data.get("village"), data.get("contact"))
        similar = similar_households(
            data.get("name"),
            data.get("ward"),
            data.get("village"),
            contact=data.get("contact"),
            address=data.get("address"),
            own_key=key,
        )
        if similar:
            self.possible_duplicates = similar
        # A shared address is handled by the hard address rule (a recorded reason), not by this tick box.
        if any(reason != "same address" for household in similar for reason in household.reasons):
            self.fields["confirm_distinct"].widget = forms.CheckboxInput(attrs={"class": "form-check-input"})
            self.add_error(
                "confirm_distinct",
                "A household with the same name or phone number is already registered. "
                "Tick this box only if this is a different household.",
            )
