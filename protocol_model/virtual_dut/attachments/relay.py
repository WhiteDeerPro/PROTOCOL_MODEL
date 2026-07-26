"""Stateless canonical-event attachment for routing VirtualDut ports."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import CanonicalEvent, SemanticFault

from .base import InterfaceAttachment
from .validation import incoming_event_fault, outgoing_event_fault


@dataclass(frozen=True)
class CanonicalEventRelayAttachment(InterfaceAttachment):
    """Validate a port-local event while preserving its canonical form.

    A relay attachment performs no cross-port routing and owns no mutable
    transaction state.  The containing backend remains responsible for route
    selection, owner tables, arbitration, and any event transformation.
    """

    protocol: InterfaceProtocol
    role: str

    def __post_init__(self) -> None:
        if self.role not in self.protocol.roles:
            raise ValueError(
                f"relay role {self.role!r} is not in protocol "
                f"{self.protocol.name!r}"
            )

    def incoming_fault(
        self,
        event: CanonicalEvent,
        *,
        rule_prefix: str = "canonical_relay",
    ) -> SemanticFault | None:
        return incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix=rule_prefix,
        )

    def outgoing_fault(
        self,
        event: CanonicalEvent,
        *,
        rule_prefix: str = "canonical_relay",
    ) -> SemanticFault | None:
        return outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix=rule_prefix,
        )


__all__ = ["CanonicalEventRelayAttachment"]
