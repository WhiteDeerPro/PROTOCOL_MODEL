"""Protocol-independent lifecycle shared by every port attachment."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent, SemanticFault


@dataclass(frozen=True)
class AttachmentEmission:
    """State and canonical events produced by one attachment operation."""

    state: object
    events: tuple[CanonicalEvent, ...] = ()
    fault: SemanticFault | None = None


class ProtocolAttachment(ABC):
    """One reusable protocol-to-operation adapter for one port role.

    Concrete operation families add their own encode/decode methods.  The
    common SPI deliberately does not pretend that address, stream, interrupt,
    and raw canonical-event attachments share one payload type.
    """

    protocol: LinkProtocol
    role: str

    def initial_state(self) -> object:
        return None

    def is_quiescent(self, state: object) -> bool:
        return True

    @property
    def incoming_event_kinds(self) -> frozenset[str]:
        return frozenset(
            channel.event.name
            for channel in self.protocol.channels.values()
            if channel.destination_role == self.role
        )

    @property
    def outgoing_event_kinds(self) -> frozenset[str]:
        return frozenset(
            channel.event.name
            for channel in self.protocol.channels.values()
            if channel.source_role == self.role
        )
