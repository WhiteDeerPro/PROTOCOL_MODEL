"""Protocol-neutral attributes carried by address operations."""

from __future__ import annotations

from dataclasses import dataclass


PROTECTION_ATTRIBUTE = "address.protection"


@dataclass(frozen=True)
class AccessProtection:
    """Common privilege, security, and instruction/data intent.

    ``None`` records that the source interface did not carry the property.
    A bridge policy must then choose an explicit target default or reject the
    operation when the target requires a value.
    """

    privileged: bool | None = None
    nonsecure: bool | None = None
    instruction: bool | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.privileged, "privileged"),
            (self.nonsecure, "nonsecure"),
            (self.instruction, "instruction"),
        ):
            if value is not None and type(value) is not bool:
                raise TypeError(
                    f"address protection {name} must be bool or None"
                )


__all__ = ["AccessProtection", "PROTECTION_ATTRIBUTE"]
