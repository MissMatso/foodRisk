"""Custom encrypted field(s) not shipped by django-encrypted-model-fields.

The library provides Encrypted{Char,Text,Date,DateTime,Email,Boolean,
Integer,...}Field but no Decimal variant. We add one here by combining
its EncryptedMixin with Django's DecimalField, matching the pattern
used for the library's other Encrypted*Field classes.
"""

from django.db import models
from encrypted_model_fields.fields import EncryptedMixin


class EncryptedDecimalField(EncryptedMixin, models.DecimalField):
    """Decimal field encrypted at rest with AES via Fernet (NFR005)."""

    pass
