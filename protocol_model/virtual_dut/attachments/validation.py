"""Validation shared by protocol-specific VirtualDut attachments."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)


def outgoing_event_fault(
    protocol: InterfaceProtocol,
    role: str,
    event: CanonicalEvent,
    *,
    rule_prefix: str = "attachment",
) -> SemanticFault | None:
    """Return why an attachment output is illegal, or ``None`` if valid.

    Attachments call this before committing interface-local state so a malformed
    emission does not leave the backend believing that a request was issued.
    """

    try:
        event_kind = protocol.event_kind_for(event.kind)
    except KeyError:
        return SemanticFault(
            f"{rule_prefix}.event_kind",
            f"attachment produced unknown event {event.kind!r} for "
            f"{protocol.name!r}",
            ConstraintScope.VIRTUAL_DUT,
        )
    if event_kind.source_role != role:
        return SemanticFault(
            f"{rule_prefix}.event_direction",
            f"protocol role {role!r} cannot emit event {event.kind!r}",
            ConstraintScope.VIRTUAL_DUT,
        )
    reasons = event_kind.schema.explain(event)
    if reasons:
        return SemanticFault(
            f"{rule_prefix}.event_schema",
            "; ".join(reasons),
            ConstraintScope.VIRTUAL_DUT,
        )
    return None


def incoming_event_fault(
    protocol: InterfaceProtocol,
    role: str,
    event: CanonicalEvent,
    *,
    rule_prefix: str = "attachment",
) -> SemanticFault | None:
    """Return why an event cannot be consumed by one attachment role."""

    try:
        event_kind = protocol.event_kind_for(event.kind)
    except KeyError:
        return SemanticFault(
            f"{rule_prefix}.event_kind",
            f"attachment received unknown event {event.kind!r} for "
            f"{protocol.name!r}",
            ConstraintScope.VIRTUAL_DUT,
        )
    if event_kind.destination_role != role:
        return SemanticFault(
            f"{rule_prefix}.event_direction",
            f"protocol role {role!r} cannot consume event {event.kind!r}",
            ConstraintScope.VIRTUAL_DUT,
        )
    reasons = event_kind.schema.explain(event)
    if reasons:
        return SemanticFault(
            f"{rule_prefix}.event_schema",
            "; ".join(reasons),
            ConstraintScope.VIRTUAL_DUT,
        )
    return None
