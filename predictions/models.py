import json

from django.db import models
from encrypted_model_fields.fields import EncryptedTextField


class Prediction(models.Model):
    """Stores a single risk prediction result — FR007."""

    CATEGORY_CHOICES = [("Low", "Low"), ("Medium", "Medium"), ("High", "High")]

    household = models.ForeignKey(
        "households.Household", on_delete=models.CASCADE, related_name="predictions"
    )
    score = models.FloatField()
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    model_version = models.CharField(max_length=50)
    explanation = models.JSONField(null=True, blank=True)
    input_snapshot = EncryptedTextField(null=True, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    feature_schema = models.CharField(max_length=50, blank=True)
    explanation_generated_at = models.DateTimeField(null=True, blank=True)
    generated_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_predictions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.household.name} — {self.category} ({self.score})"

    @property
    def income_was_estimated(self):
        """True when income was blank at scoring time, so the model filled in a typical value."""
        if not self.input_snapshot:
            return False
        try:
            return json.loads(self.input_snapshot).get("monthly_income") is None
        except (TypeError, ValueError, AttributeError):
            return False


class Intervention(models.Model):
    """Staff response and follow-up recorded after reviewing a prediction."""

    ACTION_CHOICES = [
        ("urgent_referral", "Urgent referral / food support"),
        ("programme_referral", "Programme referral"),
        ("information", "Information and guidance"),
        ("monitor", "Routine monitoring"),
    ]
    STATUS_CHOICES = [("open", "Open"), ("completed", "Completed")]
    prediction = models.ForeignKey(Prediction, on_delete=models.CASCADE, related_name="interventions")
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    notes = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="open")
    created_by = models.ForeignKey("accounts.CustomUser", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
