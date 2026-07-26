"""Directed transport connections in a system topology."""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import VirtualDutPortRef


@dataclass(frozen=True)
class DirectedTransportConnection:
    """One transmitter-to-receiver transport connection.

    This value records weak topology only.  Family-specific link activation,
    credits, lanes, or executable session state remain in the supplied
    transport profile and its owning protocol package.
    """

    name: str
    transport_family: str
    transmitter: VirtualDutPortRef
    receiver: VirtualDutPortRef
    profile: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(
                "directed transport connection requires a non-empty name"
            )
        if (
            not isinstance(self.transport_family, str)
            or not self.transport_family
        ):
            raise ValueError(
                "directed transport connection requires a non-empty family"
            )
        for endpoint, subject in (
            (self.transmitter, "transmitter"),
            (self.receiver, "receiver"),
        ):
            if not isinstance(endpoint, VirtualDutPortRef):
                raise TypeError(
                    f"transport {subject} requires VirtualDutPortRef"
                )
            if not endpoint.dut or not endpoint.port:
                raise ValueError(
                    f"transport {subject} requires DUT and port names"
                )
        if self.transmitter == self.receiver:
            raise ValueError(
                "transport transmitter and receiver must be distinct"
            )


__all__ = ["DirectedTransportConnection"]
