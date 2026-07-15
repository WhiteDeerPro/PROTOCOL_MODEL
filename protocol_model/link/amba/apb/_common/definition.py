"""Common transaction projection for concrete AMBA APB revisions."""

from __future__ import annotations

from typing import Mapping

from protocol_model.link import (
    ChannelProtocol,
    EventField,
    EventSchema,
    LinkProtocol,
)
from protocol_model.patterns import InOrderCompletionMonitor
from protocol_model.semantics import (
    BitVectorDomain,
    ConstantDomain,
    ConstraintKind,
    ConstraintScope,
    EnumDomain,
    ObligationDecl,
    ResourceDecl,
    SemanticConstraint,
    SemanticFragment,
)


APB_FAMILY = "amba.apb"


def validate_apb_dimensions(address_width: int, data_width: int) -> None:
    """Validate limits common to the published APB revisions."""

    if (
        not isinstance(address_width, int)
        or isinstance(address_width, bool)
        or not 1 <= address_width <= 32
    ):
        raise ValueError("APB address width must be between 1 and 32 bits")
    if data_width not in (8, 16, 32):
        raise ValueError("APB data width must be 8, 16, or 32 bits")


def bit_field(name: str, width: int, description: str = "") -> EventField:
    return EventField(name, BitVectorDomain(width), description)


def boolean_field(name: str, description: str = "") -> EventField:
    return EventField(name, EnumDomain((False, True)), description)


def build_apb_variant(
    name: str,
    *,
    revision: str,
    address_width: int,
    data_width: int,
    request_fields: Mapping[str, EventField] | None = None,
    write_fields: Mapping[str, EventField] | None = None,
    read_response_fields: Mapping[str, EventField] | None = None,
    write_response_fields: Mapping[str, EventField] | None = None,
    parameters: Mapping[str, object] | None = None,
    sources: tuple[str, ...],
) -> LinkProtocol:
    """Build the canonical request/completion view shared by APB revisions."""

    validate_apb_dimensions(address_width, data_width)
    read_payload = {
        "addr": bit_field("addr", address_width, "byte address"),
        **(request_fields or {}),
    }
    write_payload = {
        **read_payload,
        "data": bit_field("data", data_width, "write data"),
        **(write_fields or {}),
    }
    read_response_payload = {
        "data": bit_field("data", data_width, "read data"),
        "error": boolean_field("error", "normalized PSLVERR"),
        **(read_response_fields or {}),
    }
    write_response_payload = {
        "error": boolean_field("error", "normalized PSLVERR"),
        **(write_response_fields or {}),
    }
    channels = {
        "READ": ChannelProtocol(
            "READ",
            "requester",
            "completer",
            EventSchema("READ", read_payload, ConstantDomain(None)),
        ),
        "WRITE": ChannelProtocol(
            "WRITE",
            "requester",
            "completer",
            EventSchema("WRITE", write_payload, ConstantDomain(None)),
        ),
        "READ_RESPONSE": ChannelProtocol(
            "READ_RESPONSE",
            "completer",
            "requester",
            EventSchema(
                "READ_RESPONSE", read_response_payload, ConstantDomain(None)
            ),
        ),
        "WRITE_RESPONSE": ChannelProtocol(
            "WRITE_RESPONSE",
            "completer",
            "requester",
            EventSchema(
                "WRITE_RESPONSE", write_response_payload, ConstantDomain(None)
            ),
        ),
    }
    monitor = InOrderCompletionMonitor(
        "apb.transfer",
        {"READ": "READ_RESPONSE", "WRITE": "WRITE_RESPONSE"},
        "apb.pending_transfer",
        1,
    )
    fragment = SemanticFragment(
        f"{name}.link_semantics",
        constraints=(
            SemanticConstraint(
                f"{name}.single_outstanding",
                "one APB transfer completes before the next transfer begins",
                ConstraintScope.LINK,
                kind=ConstraintKind.RESOURCE,
                targets=("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"),
            ),
            SemanticConstraint(
                f"{name}.response_direction",
                "read transfers return read data and writes return write completion",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"),
            ),
            SemanticConstraint(
                f"{name}.in_order",
                "the completion belongs to the sole pending transfer",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("READ_RESPONSE", "WRITE_RESPONSE"),
            ),
        ),
        resources=(
            ResourceDecl(
                "apb.pending_transfer",
                ConstraintScope.LINK,
                capacity=1,
                description="transfer observed in SETUP and awaiting completed ACCESS",
                acquired_by=("READ or WRITE",),
                released_by=("matching response", "reset"),
            ),
        ),
        obligations=(
            ObligationDecl(
                f"{name}.read_completion",
                ConstraintScope.LINK,
                "READ",
                "READ_RESPONSE",
                "an APB read completes in an ACCESS phase",
            ),
            ObligationDecl(
                f"{name}.write_completion",
                ConstraintScope.LINK,
                "WRITE",
                "WRITE_RESPONSE",
                "an APB write completes in an ACCESS phase",
            ),
        ),
        sources=sources,
    )
    return LinkProtocol.define(
        name,
        family=APB_FAMILY,
        roles=frozenset(("requester", "completer")),
        channels=channels,
        fragments=(fragment,),
        parameters={
            "address_width": address_width,
            "data_width": data_width,
            "revision": revision,
            **(parameters or {}),
        },
        monitors={monitor.name: monitor},
    )
