"""Stable names for participant-owned CHI progress resources."""

from __future__ import annotations


_CACHE_LINE_BYTES = 64


def chi_line_resource_name(participant: str, address: int) -> str:
    """Return the canonical resource name for one participant-local line.

    A Home reservation and an RN reservation are different resources even
    when they refer to the same address.  ``participant`` therefore names the
    component that owns the transient state rather than a topology binding or
    the enclosing system session.
    """

    if not isinstance(participant, str) or not participant:
        raise ValueError("CHI line resource requires a participant name")
    if (
        not isinstance(address, int)
        or isinstance(address, bool)
        or address < 0
        or address % _CACHE_LINE_BYTES
    ):
        raise ValueError(
            "CHI line resource address must be 64-byte aligned"
        )
    return f"{participant}.line[{address:#x}]"


__all__ = ["chi_line_resource_name"]
