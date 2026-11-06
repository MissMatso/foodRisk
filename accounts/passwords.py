"""Temporary passwords handed out by an administrator."""

import secrets

# No 0/O/1/l/I: a temporary password is often read aloud or copied by hand.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temporary_password(length=12):
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
