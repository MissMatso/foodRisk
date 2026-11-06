from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.roles import sees_personal_details
from households.models import Household
from predictions.models import Prediction


class HouseholdSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        # Validate a merged copy for PATCH as well as complete POST/PUT requests.
        values = (
            {f.attname: getattr(self.instance, f.attname) for f in Household._meta.concrete_fields}
            if self.instance
            else {}
        )
        values.update(attrs)
        candidate = Household(**values)
        if self.instance:
            # This copy stands for an existing record. Without this, Django's unique checks
            # treat it as a new row that clashes with itself ("Household with this ID already exists").
            candidate._state.adding = False
        try:
            candidate.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None and not sees_personal_details(request.user):
            data.pop("address", None)  # analysts work with scores and trends, not a household's whereabouts
            data.pop("contact", None)
        return data

    class Meta:
        model = Household
        fields = [
            "id",
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
            "created_at",
            "updated_at",
        ]


class PredictionSerializer(serializers.ModelSerializer):
    household_name = serializers.CharField(source="household.name", read_only=True)

    class Meta:
        model = Prediction
        fields = [
            "id",
            "household",
            "household_name",
            "score",
            "category",
            "model_version",
            "explanation",
            "explanation_generated_at",
            "created_at",
        ]
        read_only_fields = ["score", "category", "model_version", "explanation", "created_at"]
