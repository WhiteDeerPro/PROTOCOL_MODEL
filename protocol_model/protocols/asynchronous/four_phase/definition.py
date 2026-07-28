"""Canonical transfer language for a four-phase asynchronous token interface.

The four REQ/ACK levels are a wire encoding.  They are deliberately checked by
``FourPhaseObserver`` instead of appearing as four canonical event kinds.  One
complete request/acknowledge exchange lowers to one ``TRANSFER`` event, just as
a ready/valid acceptance lowers to one channel event.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import (
    InterfaceEventKind,
    InterfaceProtocol,
)
from protocol_model.semantics import (
    BitVectorDomain,
    ConstraintKind,
    ConstraintScope,
    EventField,
    EventSchema,
    NaturalDomain,
    SemanticConstraint,
    SemanticFragment,
)


FOUR_PHASE_TOKEN_FAMILY = "asynchronous.four_phase_token"


@dataclass(frozen=True)
class FourPhaseTokenConfig:
    """Optional bundled payload carried by one serialized token transfer.

    ``data_width=None`` constructs a control-only token.  The event key is a
    model-side occurrence label; it is not an additional wire signal.
    """

    data_width: int | None = None

    def __post_init__(self) -> None:
        if self.data_width is not None and (
            not isinstance(self.data_width, int)
            or isinstance(self.data_width, bool)
            or self.data_width <= 0
        ):
            raise ValueError("data_width must be a positive integer or None")


def build_four_phase_token_interface(
    config: FourPhaseTokenConfig | None = None,
) -> InterfaceProtocol:
    """Build the canonical side of a serialized four-phase token channel.

    The returned protocol can be attached to ``sender`` and ``receiver``
    ``InterfacePort`` objects.  Raw REQ/ACK ordering is validated by the
    observation profile; an InterfaceSession consumes only accepted TRANSFER events.
    """

    config = config or FourPhaseTokenConfig()
    fields = {}
    if config.data_width is not None:
        fields["data"] = EventField(
            "data",
            BitVectorDomain(config.data_width),
            "optional bundled data captured for this token",
        )
    transfer = EventSchema(
        "TRANSFER",
        fields,
        key=NaturalDomain(),
    )
    fragment = SemanticFragment(
        "four_phase_token.transfer_semantics",
        constraints=(
            SemanticConstraint(
                "four_phase_token.acceptance",
                "one TRANSFER denotes one receiver acknowledgement in a legal "
                "four-phase return-to-zero exchange",
                ConstraintScope.INTERFACE,
                targets=("TRANSFER",),
            ),
            SemanticConstraint(
                "four_phase_token.serialization",
                "a new token is not accepted until REQ and ACK have returned "
                "to their idle levels",
                ConstraintScope.INTERFACE,
                kind=ConstraintKind.RELATION,
                targets=("TRANSFER",),
            ),
        ),
        sources=(
            "four-phase return-to-zero request/acknowledge convention",
        ),
    )
    return InterfaceProtocol.define(
        "four_phase_token",
        interface_family=FOUR_PHASE_TOKEN_FAMILY,
        roles=frozenset(("sender", "receiver")),
        event_kinds={
            "transfer": InterfaceEventKind(
                "transfer", "sender", "receiver", transfer
            )
        },
        fragments=(fragment,),
        parameters={
            "data_width": config.data_width,
            "wire_encoding": "four_phase_return_to_zero",
            "maximum_wire_in_flight": 1,
        },
    )


__all__ = [
    "FOUR_PHASE_TOKEN_FAMILY",
    "FourPhaseTokenConfig",
    "build_four_phase_token_interface",
]
