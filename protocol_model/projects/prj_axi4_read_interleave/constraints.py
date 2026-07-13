"""Project-owned constraints derived from the reusable AXI4 protocol spec."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.domains import ConstantDomain, EnumDomain, EventSpace
from protocol_model.protocols.spec import (
    ConstraintRecord,
    ProtocolDerivation,
    ProtocolSpec,
)
from protocol_model.semantics import CardinalityObligation


@dataclass(frozen=True)
class ReadInterleaveConstraints:
    """Constraints specific to this experiment, not universal AXI4 rules."""

    active_ids: tuple[int, ...] = (1, 2)
    quiet_channels: tuple[str, ...] = ("AW", "W", "B")
    quiet_ar_fields: tuple[tuple[str, int], ...] = (
        ("lock", 0),
        ("cache", 0),
        ("prot", 0),
        ("qos", 0),
        ("region", 0),
    )

    def __post_init__(self) -> None:
        if len(self.active_ids) < 2 or len(set(self.active_ids)) != len(
            self.active_ids
        ):
            raise ValueError("read interleaving needs at least two unique active IDs")
        if set(self.quiet_channels) - {"AW", "W", "B"}:
            raise ValueError("the read-only experiment may quiet only AW/W/B")


@dataclass(frozen=True)
class QuietChannelMonitor(SemanticComponent[CanonicalEvent, None, CanonicalEvent]):
    name: str
    event_kinds: frozenset[str]

    def initial_state(self) -> None:
        return None

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def step(
        self, state: None, event: CanonicalEvent
    ) -> SemanticStep[None, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.quiet_channel",
                f"{event.kind} is tied inactive by the read-only experiment",
                scope="PROFILE",
            ),
        )


def derive_constrained_axi4(
    base: ProtocolSpec, constraints: ReadInterleaveConstraints
) -> ProtocolSpec:
    """Derive a read-only experiment spec without changing base AXI4."""

    id_width = int(base.parameters["id_width"])
    limit = 1 << id_width
    if any(
        type(item) is not int or not 0 <= item < limit
        for item in constraints.active_ids
    ):
        raise ValueError(f"active IDs must fit AXI ID width {id_width}")

    active_ids = EnumDomain(constraints.active_ids)
    base_ar = base.channel("AR").transfer
    ar_payload = dict(base_ar.payload)
    for name, value in constraints.quiet_ar_fields:
        if name not in ar_payload or not ar_payload[name].contains(value):
            raise ValueError(f"cannot tie AR field {name!r} to {value!r}")
        ar_payload[name] = ConstantDomain(value)
    ar = EventSpace(
        base_ar.kind,
        active_ids,
        ar_payload,
        base_ar.constraints,
        base_ar.allow_extra_payload,
    )

    base_r = base.channel("R").transfer
    r = EventSpace(
        base_r.kind,
        active_ids,
        base_r.payload,
        base_r.constraints,
        base_r.allow_extra_payload,
    )
    read = CardinalityObligation(
        "axi4.read_beats",
        ar,
        r,
        count_of=lambda event: int(event.payload["len"]) + 1,
        final_field="last",
    )
    quiet = QuietChannelMonitor(
        "axi4.read_interleave_profile",
        frozenset(
            base.channel(name).transfer.kind for name in constraints.quiet_channels
        ),
    )
    derivation = ProtocolDerivation(base, "axi4_read_interleave")
    derivation.replace_ready_valid_channel("AR", ar)
    derivation.replace_ready_valid_channel("R", r)
    derivation.replace_transaction_model("read", read)
    derivation.add_transaction_model("read_profile_quiet", quiet)
    derivation.constrain(
        ConstraintRecord(
            "project_active_ids",
            "ARID/RID are restricted to the experiment active ID set",
            ("AR.id", "R.id"),
            "ProjectProfile",
        )
    )
    derivation.constrain(
        ConstraintRecord(
            "project_quiet_ar_sidebands",
            "unused AR sidebands are tied to Boolean/integer zero",
            tuple(f"AR.{name}" for name, _ in constraints.quiet_ar_fields),
            "ConstantDomain",
        )
    )
    derivation.constrain(
        ConstraintRecord(
            "project_quiet",
            "AW/W/B VALID remain inactive",
            tuple(f"{name}.valid" for name in constraints.quiet_channels),
            "QuietChannelMonitor",
        )
    )
    derivation.set_parameter("active_read_ids", constraints.active_ids)
    derivation.set_parameter("quiet_channels", constraints.quiet_channels)
    derivation.set_parameter("quiet_ar_fields", constraints.quiet_ar_fields)
    return derivation.build()
