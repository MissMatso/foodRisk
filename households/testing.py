"""Helpers shared by the test suites."""

import itertools

_numbers = itertools.count(1)


def unique_address(street="Fixture St"):
    """A street address no other test household uses, so the shared-address rule stays out of the way."""
    return f"{next(_numbers)} {street}"
