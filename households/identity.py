"""Duplicate-household detection.

Address and contact are encrypted at rest (NFR005), so the database cannot
enforce uniqueness on them directly. Instead each household stores an
`identity_key`: a keyed hash (HMAC-SHA256, a "blind index") of its normalised
name, ward, village and contact number. The database enforces that key is
unique, so a duplicate is refused even if two staff members submit at the
same moment, and the contact number is never stored in readable form.

Two levels of protection:
  * hard rule  - identical identity key: the record is refused;
  * soft rule  - same normalised name in the same ward and village but a
                 different contact number: staff must confirm it is a
                 different household (web form only).
"""

import hashlib
import hmac
import re
import unicodedata

from django.conf import settings


def normalise_text(value):
    """Case, accents, punctuation and spacing differences must not hide a duplicate."""
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[^\w\s]", "", value)
    return " ".join(value.split())


def normalise_contact(value):
    """Digits only, and +27 71 111 2222 is treated the same as 071 111 2222."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("27") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def is_valid_contact(value):
    """A South African phone number: 10 digits starting 0, or +27 followed by 9 digits."""
    return bool(re.fullmatch(r"0\d{9}", normalise_contact(value)))


_ADDRESS_WORDS = {
    "road": "rd",
    "street": "st",
    "avenue": "ave",
    "drive": "dr",
    "lane": "ln",
    "crescent": "cres",
    "extension": "ext",
}
# Entries that say nothing about where a household is, so they must never "match" each other.
_EMPTY_ADDRESSES = {"na", "n a", "none", "nil", "unknown", "no address", "not applicable", "no fixed address"}


def normalise_address(value):
    """'12 Main Road.' and '12 main rd' are the same address."""
    words = [_ADDRESS_WORDS.get(word, word) for word in normalise_text(value).split()]
    return " ".join(words)


def _secret(domain="household-identity"):
    key = settings.FIELD_ENCRYPTION_KEY
    if isinstance(key, (list, tuple)):
        key = key[0]
    if isinstance(key, str):
        key = key.encode()
    # Tied to the encryption key, which cannot change without losing the data anyway.
    # A different label per purpose, so one kind of key cannot be compared with another.
    return hashlib.sha256(domain.encode() + b"|" + key).digest()


def identity_key(name, ward, village, contact):
    """The blind index, or None when there is not enough to identify a household."""
    parts = [normalise_text(name), normalise_text(ward), normalise_text(village), normalise_contact(contact)]
    if not parts[0] or not parts[3]:
        return None
    return hmac.new(_secret(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def contact_key(contact):
    """Keyed hash of the phone number alone, to spot one number used by several households."""
    digits = normalise_contact(contact)
    if len(digits) < 9:
        return None
    return hmac.new(_secret("household-contact"), digits.encode(), hashlib.sha256).hexdigest()


def address_key(address, village):
    """Keyed hash of address + village, or None when the address says nothing useful."""
    text = normalise_address(address)
    if len(text) < 6 or text in _EMPTY_ADDRESSES:
        return None
    return hmac.new(
        _secret("household-address"), f"{text}|{normalise_text(village)}".encode(), hashlib.sha256
    ).hexdigest()


def similar_households(name, ward, village, contact="", address="", own_key=None, exclude_pk=None, limit=5):
    """Other households that might be the same family. Each result has `.reasons`.

    Reasons: the same name in the same ward and village, the same phone number,
    or the same address in the same village. An exact identity match is left out,
    because the hard rule already refuses that. Only plain columns and keys are
    read, so no encrypted field is decrypted.
    """
    from .models import Household

    def others():
        queryset = Household.objects.all()
        return queryset.exclude(pk=exclude_pk) if exclude_pk else queryset

    found = {}

    def add(household, reason):
        if own_key and household.identity_key == own_key:
            return
        household.reasons = getattr(household, "reasons", [])
        found.setdefault(household.pk, household)
        if reason not in found[household.pk].reasons:
            found[household.pk].reasons.append(reason)

    same_place = others().filter(ward__iexact=(ward or "").strip(), village__iexact=(village or "").strip())
    target = normalise_text(name)
    for household in same_place.only("id", "name", "ward", "village", "identity_key"):
        if normalise_text(household.name) == target:
            add(household, "same name")
    phone, place = contact_key(contact), address_key(address, village)
    if phone:
        for household in (
            others().filter(contact_key=phone).only("id", "name", "ward", "village", "identity_key")
        ):
            add(household, "same phone number")
    if place:
        for household in (
            others().filter(address_key=place).only("id", "name", "ward", "village", "identity_key")
        ):
            add(household, "same address")
    return list(found.values())[:limit]
