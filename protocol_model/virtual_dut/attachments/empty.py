"""Explicit empty endpoint intent for topology and hang-oriented fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from protocol_model.link import LinkProtocol

from .base import ProtocolAttachment


class EmptyEndpointMode(str, Enum):
    """Two intentionally different forms of locally empty behavior."""

    IDLE_SOURCE = "idle_source"
    BLACKHOLE_SINK = "blackhole_sink"


@dataclass(frozen=True)
class EmptyEndpointAttachment(ProtocolAttachment):
    """Declare a port whose local backend produces no follow-up events.

    An idle source has no autonomous emission in the current synchronous
    backend model.  A blackhole sink consumes incoming canonical events and
    deliberately leaves request/completion obligations unresolved.  This is
    canonical-event behavior; a pin-level VALID-tied-low policy belongs to an
    observation/driver adapter.
    """

    protocol: LinkProtocol
    role: str
    mode: EmptyEndpointMode

    def __post_init__(self) -> None:
        if not isinstance(self.mode, EmptyEndpointMode):
            object.__setattr__(self, "mode", EmptyEndpointMode(self.mode))
        if self.role not in self.protocol.roles:
            raise ValueError(
                f"empty endpoint role {self.role!r} is not in protocol "
                f"{self.protocol.name!r}"
            )
        if self.mode is EmptyEndpointMode.IDLE_SOURCE:
            if not self.outgoing_event_kinds:
                raise ValueError("idle source role has no outgoing protocol events")
        elif not self.incoming_event_kinds:
            raise ValueError("blackhole sink role has no incoming protocol events")
