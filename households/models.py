from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, models, transaction
from encrypted_model_fields.fields import EncryptedBooleanField, EncryptedCharField

from .fields import EncryptedDecimalField
from .identity import address_key, contact_key, identity_key, is_valid_contact
from .locations import canonical
from ml_engine.features import PROVINCES

# Plausibility limits: catch typing slips such as an extra zero.
MAX_MONTHLY_INCOME = 500_000
MAX_HOUSEHOLD_SIZE = 30
MAX_DISTANCE_KM = 500


class Household(models.Model):
    """Household record — FR002, FR003, FR004.

    address, contact and monthly_income are encrypted at rest with Fernet
    (NFR005) via django-encrypted-model-fields.

    The active demonstration model uses ml_engine.simulated_features.
    Other fields support case administration and are not model predictors.
    """

    EMPLOYMENT_CHOICES = [
        ("employed", "Employed"),
        ("unemployed", "Unemployed"),
        ("informal", "Informal"),
        ("grant_only", "Grant Only"),
    ]

    WATER_ACCESS_CHOICES = [
        ("piped", "Piped (in-house or yard)"),
        ("communal", "Communal tap"),
        ("borehole", "Borehole"),
        ("river", "River / open source"),
        ("none", "Unknown / no reliable access"),
        ("other", "Other drinking-water source"),
    ]

    name = models.CharField(max_length=200)
    address = EncryptedCharField(max_length=500)
    contact = EncryptedCharField(max_length=20)
    ward = models.CharField(max_length=100, blank=True)
    village = models.CharField(max_length=100, blank=True)

    province = models.CharField(max_length=1, choices=PROVINCES, default="3")
    monthly_income = EncryptedDecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leave blank if unknown. The model imputes missing income; never enter a made-up value.",
    )
    household_size = models.PositiveIntegerField()
    num_dependents = models.PositiveIntegerField()
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_CHOICES)

    has_disabled_member = EncryptedBooleanField(default=False)
    has_chronic_illness = EncryptedBooleanField(default=False)
    children_under_5 = models.PositiveIntegerField(default=0)
    elderly_members = models.PositiveIntegerField("Members aged 60 or older", default=0)
    distance_to_market_km = models.PositiveIntegerField(default=0)
    water_access = models.CharField(max_length=20, choices=WATER_ACCESS_CHOICES, default="piped")
    land_ownership = models.BooleanField(default=False)

    # Keyed hash of name + ward + village + contact (see households/identity.py).
    # Lets the database refuse duplicates without storing the contact number readably.
    identity_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    # Keyed hashes of the phone number and of address + village. Not unique (families legitimately
    # share both), but they let registration warn "this number / address is already used".
    contact_key = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    address_key = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    # The address is the main duplicate control: a second household at the same address in the same
    # village is refused unless staff record why it is a separate household (e.g. "backyard room 2").
    shared_address_reason = models.CharField(
        "Reason for sharing an address",
        max_length=200,
        blank=True,
        help_text=(
            "Only needed when another household is already registered at this address, "
            "for example a backyard room or a separate flat."
        ),
    )

    registered_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_households",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        # The database itself refuses impossible numbers, even if a script skips the form and clean().
        # (Income is encrypted, so its rule can only be checked in clean().)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(household_size__gte=1), name="household_size_at_least_one"
            ),
            models.CheckConstraint(
                condition=models.Q(num_dependents__lte=models.F("household_size")),
                name="dependents_within_household_size",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    household_size__gte=models.F("children_under_5") + models.F("elderly_members")
                ),
                name="children_and_elderly_within_household_size",
            ),
        ]

    def clean(self):
        errors = {}
        if self.monthly_income is not None and self.monthly_income < 0:
            errors["monthly_income"] = "Income must be ≥ 0."
        if self.household_size is not None and self.household_size <= 0:
            errors["household_size"] = "Household size must be > 0."
        if (
            self.household_size is not None
            and self.num_dependents is not None
            and self.num_dependents > self.household_size
        ):
            errors["num_dependents"] = "Dependents cannot exceed household size."
        counted_dependents = (self.children_under_5 or 0) + (self.elderly_members or 0)
        if self.household_size is not None and counted_dependents > self.household_size:
            errors["elderly_members"] = "Children and elderly members cannot exceed household size."
        if self.num_dependents is not None and counted_dependents > self.num_dependents:
            errors["num_dependents"] = "Dependents must include children and elderly members."
        # One spelling per ward and village, whatever case or spacing was typed.
        self.ward = canonical(self.ward, "ward")
        self.village = canonical(self.village, "village", ward=self.ward)
        if self.monthly_income is not None and self.monthly_income > MAX_MONTHLY_INCOME:
            errors["monthly_income"] = (
                f"Income above R{MAX_MONTHLY_INCOME:,} a month looks like a typing error. Please check it."
            )
        if self.household_size is not None and self.household_size > MAX_HOUSEHOLD_SIZE:
            errors["household_size"] = f"Household size above {MAX_HOUSEHOLD_SIZE} looks like a typing error."
        if self.distance_to_market_km is not None and self.distance_to_market_km > MAX_DISTANCE_KM:
            errors["distance_to_market_km"] = (
                f"A distance above {MAX_DISTANCE_KM} km looks like a typing error."
            )
        if self.contact and not is_valid_contact(self.contact):
            errors["contact"] = (
                "Enter a valid South African phone number, for example 071 111 2222 or +27 71 111 2222."
            )
        self.shared_address_reason = " ".join((self.shared_address_reason or "").split())
        sharing = self.households_at_same_address()
        if sharing and not self.shared_address_reason:
            first = sharing[0]
            place = first.village or "this village"
            errors["shared_address_reason"] = (
                f"Another household is already registered at this address in {place} "
                f"(record {first.pk}: {first.name}). If this is the same family, open that record instead. "
                "If it is a separate household living at the same address, give the reason here."
            )
        existing = self.find_duplicate()
        if existing:
            errors[NON_FIELD_ERRORS] = (
                f"This household is already registered (record {existing.pk}: {existing.name}). "
                "Open that record instead of registering it again."
            )
        if errors:
            raise ValidationError(errors)

    def current_identity_key(self):
        return identity_key(self.name, self.ward, self.village, self.contact)

    def find_duplicate(self):
        """Another household with the same name, ward, village and contact number, or None."""
        key = self.current_identity_key()
        if not key:
            return None
        return Household.objects.filter(identity_key=key).exclude(pk=self.pk).first()

    def households_at_same_address(self):
        """Other households registered at the same (normalised) address in the same village."""
        key = address_key(self.address, self.village)
        if not key:
            return []
        return list(
            Household.objects.filter(address_key=key).exclude(pk=self.pk).only("id", "name", "village")
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        self.identity_key = self.current_identity_key()
        self.contact_key = contact_key(self.contact)
        self.address_key = address_key(self.address, self.village)
        try:
            # Signals run inside this transaction: audit failure rolls back the record.
            with transaction.atomic():
                super().save(*args, **kwargs)
        except IntegrityError as exc:
            # Two people saved the same household at the same moment: the database rule caught it.
            if "identity_key" in str(exc):
                raise ValidationError(
                    {NON_FIELD_ERRORS: "This household has just been registered by someone else."}
                ) from exc
            raise

    @property
    def income_per_capita(self):
        if self.monthly_income is None:
            return None
        if self.household_size:
            return float(self.monthly_income) / self.household_size
        return 0.0

    @property
    def latest_prediction(self):
        return self.predictions.order_by("-created_at").first()

    def __str__(self):
        return self.name


class AuditLog(models.Model):
    """Audit trail entry for a household create/update/delete — matches
    the AuditLog entity in the Phase 2 ERD (User, Household, Prediction,
    AuditLog) and closes the 'no audit trail' gap from Phase 1.

    `household` is nullable because a deleted household's FK would
    otherwise be dangling; `household_name` is kept as a plain snapshot
    so the log entry stays readable after deletion.
    """

    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_CHOICES = [
        (ACTION_CREATE, "Created"),
        (ACTION_UPDATE, "Updated"),
        (ACTION_DELETE, "Deleted"),
    ]

    household = models.ForeignKey(
        Household,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    household_name = models.CharField(max_length=200)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey(
        "accounts.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="household_audit_actions",
    )
    changes = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        who = self.changed_by.username if self.changed_by else "system"
        when = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return f"{self.get_action_display()} — {self.household_name} by {who} at {when}"
