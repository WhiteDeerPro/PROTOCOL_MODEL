"""Protocol-independent lifecycle shared by every port attachment."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import CanonicalEvent, SemanticFault


@dataclass(frozen=True)
class AttachmentEmission:
    """State and canonical events produced by one attachment operation."""

    state: object
    events: tuple[CanonicalEvent, ...] = ()
    fault: SemanticFault | None = None


class InterfaceAttachment(ABC):
    """One reusable protocol-to-operation adapter for one port role.

    Concrete operation families add their own encode/decode methods.  The
    common SPI deliberately does not pretend that address, stream, interrupt,
    and raw canonical-event attachments share one payload type.
    """

    protocol: InterfaceProtocol
    role: str

    def initial_state(self) -> object:
        return None

    def is_quiescent(self, state: object) -> bool:
        return True

    @property
    def incoming_event_kinds(self) -> frozenset[str]:
        return frozenset(
            event_kind.schema.name
            for event_kind in self.protocol.event_kinds.values()
            if event_kind.destination_role == self.role
        )

    @property
    def outgoing_event_kinds(self) -> frozenset[str]:
        return frozenset(
            event_kind.schema.name
            for event_kind in self.protocol.event_kinds.values()
            if event_kind.source_role == self.role
        )
