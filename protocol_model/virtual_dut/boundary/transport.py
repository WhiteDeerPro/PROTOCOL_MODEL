"""Transport-facing ports on a concrete VirtualDut boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TransportDirection(str, Enum):
    """Direction of one unidirectional transport port."""

    TRANSMIT = "transmit"
    RECEIVE = "receive"


@dataclass(frozen=True)
class TransportPort:
    """One unidirectional transport endpoint on a VirtualDut boundary.

    ``transport_family`` identifies the compatible transport contract without
    making this generic boundary depend on a concrete protocol package.  A
    family-specific capability profile can be carried separately.
    """

    name: str
    transport_family: str
    direction: TransportDirection
    capability: object | None = field(default=None, repr=False)
    clock_domain: str | None = None
    reset_domain: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("transport port requires a non-empty name")
        if (
            not isinstance(self.transport_family, str)
            or not self.transport_family
        ):
            raise ValueError(
                "transport port requires a non-empty transport family"
            )
        try:
            direction = TransportDirection(self.direction)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "transport port direction must be transmit or receive"
            ) from error
        for value, subject in (
            (self.clock_domain, "clock domain"),
            (self.reset_domain, "reset domain"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value
            ):
                raise ValueError(
                    f"transport port {subject} must be a non-empty string"
                )
        object.__setattr__(self, "direction", direction)


__all__ = ["TransportDirection", "TransportPort"]
