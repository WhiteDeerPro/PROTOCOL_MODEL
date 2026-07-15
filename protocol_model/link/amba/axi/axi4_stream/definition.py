"""AXI4-Stream schemas, byte qualifiers, packets, and ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Tuple

from protocol_model.link import ChannelProtocol, EventField, EventSchema, LinkProtocol
from protocol_model.semantics import (
    BitVectorDomain,
    CanonicalEvent,
    ConstantDomain,
    ConstraintKind,
    ConstraintScope,
    EnumDomain,
    EventConstraint,
    EventOffer,
    ResourceDecl,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)


AXI4_STREAM_FAMILY = "amba.axi4_stream"


@dataclass(frozen=True)
class Axi4StreamConfig:
    data_width: int = 32
    id_width: int = 0
    dest_width: int = 0
    user_width: int = 0
    use_keep: bool = False
    use_strb: bool = False
    use_last: bool = True

    def __post_init__(self) -> None:
        if self.data_width <= 0 or self.data_width % 8:
            raise ValueError(
                "AXI4-Stream data width must be a positive integer number of bytes"
            )
        for name, width in (
            ("id_width", self.id_width),
            ("dest_width", self.dest_width),
            ("user_width", self.user_width),
        ):
            if width < 0:
                raise ValueError(f"AXI4-Stream {name} must not be negative")

    @property
    def bytes_per_transfer(self) -> int:
        return self.data_width // 8


def _effective_keep(event: CanonicalEvent, byte_count: int) -> int:
    return int(event.payload.get("keep", (1 << byte_count) - 1))


def _effective_strb(event: CanonicalEvent, byte_count: int) -> int:
    keep = _effective_keep(event, byte_count)
    return int(event.payload.get("strb", keep))


def _qualifiers_are_legal(event: CanonicalEvent, byte_count: int) -> bool:
    keep = _effective_keep(event, byte_count)
    strb = _effective_strb(event, byte_count)
    return strb & ~keep == 0


def _stream_schema(config: Axi4StreamConfig) -> EventSchema:
    fields = {
        "data": EventField("data", BitVectorDomain(config.data_width)),
    }
    if config.use_keep:
        fields["keep"] = EventField(
            "keep", BitVectorDomain(config.bytes_per_transfer)
        )
    if config.use_strb:
        fields["strb"] = EventField(
            "strb", BitVectorDomain(config.bytes_per_transfer)
        )
    if config.use_last:
        fields["last"] = EventField("last", EnumDomain((False, True)))
    if config.dest_width:
        fields["dest"] = EventField("dest", BitVectorDomain(config.dest_width))
    if config.user_width:
        fields["user"] = EventField("user", BitVectorDomain(config.user_width))
    key = (
        BitVectorDomain(config.id_width)
        if config.id_width
        else ConstantDomain(None)
    )
    return EventSchema(
        "T",
        fields,
        key,
        (
            EventConstraint(
                "byte_qualifiers",
                lambda event: _qualifiers_are_legal(
                    event, config.bytes_per_transfer
                ),
                "TSTRB must not mark a byte whose TKEEP value is low",
            ),
        ),
    )


StreamFlow = Tuple[Hashable, int]


def _flow_of(event: CanonicalEvent) -> StreamFlow:
    return event.key, int(event.payload.get("dest", 0))


@dataclass(frozen=True)
class Axi4StreamPacketState:
    open_packets: tuple[tuple[StreamFlow, int], ...] = ()
    previous_transfer: int | None = None


@dataclass(frozen=True)
class Axi4StreamPacketMonitor(
    SemanticComponent[CanonicalEvent, Axi4StreamPacketState, object]
):
    name: str
    use_last: bool
    resource_name: str = "axi4_stream.open_packets"

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("T",))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind == "T"

    def initial_state(self) -> Axi4StreamPacketState:
        return Axi4StreamPacketState()

    def is_quiescent(self, state: Axi4StreamPacketState) -> bool:
        return not self.use_last or not state.open_packets

    def resource_usage(self, state: Axi4StreamPacketState) -> dict[str, int]:
        if not self.use_last:
            return {}
        return {self.resource_name: len(state.open_packets)}

    def event_offers(self, _state: Axi4StreamPacketState) -> tuple[EventOffer, ...]:
        return (EventOffer.unconstrained("T"),)

    def step(
        self, state: Axi4StreamPacketState, event: CanonicalEvent
    ) -> SemanticStep[Axi4StreamPacketState, object]:
        if event.kind != "T":
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.alphabet",
                    f"expected 'T', got {event.kind!r}",
                    ConstraintScope.LINK,
                ),
            )
        if event.trace_index is None:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.trace_index",
                    "stream transfers must be normalized by a LinkSession",
                    ConstraintScope.LINK,
                ),
            )

        packets = dict(state.open_packets)
        if self.use_last:
            flow = _flow_of(event)
            if bool(event.payload["last"]):
                packets.pop(flow, None)
            else:
                packets[flow] = event.trace_index
        predecessors = (
            ()
            if state.previous_transfer is None
            else (state.previous_transfer,)
        )
        return SemanticStep(
            Axi4StreamPacketState(
                tuple(packets.items()), event.trace_index
            ),
            causal_predecessors=predecessors,
        )


@dataclass(frozen=True)
class Axi4StreamContinuousState:
    current_flow: StreamFlow | None = None


@dataclass(frozen=True)
class Axi4StreamContinuousMonitor(
    SemanticComponent[CanonicalEvent, Axi4StreamContinuousState, object]
):
    name: str
    byte_count: int
    id_present: bool
    dest_present: bool

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("T",))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind == "T"

    def initial_state(self) -> Axi4StreamContinuousState:
        return Axi4StreamContinuousState()

    def is_quiescent(self, state: Axi4StreamContinuousState) -> bool:
        return state.current_flow is None

    def event_offers(
        self, state: Axi4StreamContinuousState
    ) -> tuple[EventOffer, ...]:
        if state.current_flow is None:
            return (EventOffer.unconstrained("T"),)
        key, dest = state.current_flow
        payload = {"dest": dest} if self.dest_present else {}
        return (
            EventOffer.constrained(
                "T", key=key if self.id_present else None, payload=payload
            ),
        )

    def step(
        self, state: Axi4StreamContinuousState, event: CanonicalEvent
    ) -> SemanticStep[Axi4StreamContinuousState, object]:
        flow = _flow_of(event)
        if state.current_flow is not None and flow != state.current_flow:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.packet_interleave",
                    "TID or TDEST changed before the current packet reached TLAST",
                    ConstraintScope.LINK,
                ),
            )
        keep = _effective_keep(event, self.byte_count)
        all_bytes = (1 << self.byte_count) - 1
        last = bool(event.payload["last"])
        if not last and keep != all_bytes:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.interior_null_byte",
                    "a non-final continuous-packet transfer must keep every byte",
                    ConstraintScope.LINK,
                ),
            )
        if last and keep & (keep + 1):
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.final_null_byte_position",
                    "final continuous-packet null bytes must be above all kept bytes",
                    ConstraintScope.LINK,
                ),
            )
        return SemanticStep(
            Axi4StreamContinuousState(None if last else flow)
        )


def build_axi4_stream_link(
    config: Axi4StreamConfig | None = None,
) -> LinkProtocol:
    """Build the base AXI4-Stream LinkProtocol.

    Different TID/TDEST streams may interleave. The accepted transfer order is
    retained globally, and an unfinished explicit packet keeps a trace
    inconclusive rather than invalid.
    """

    config = config or Axi4StreamConfig()
    channel = ChannelProtocol(
        "T", "transmitter", "receiver", _stream_schema(config)
    )
    packet_monitor = Axi4StreamPacketMonitor(
        "axi4_stream.packet", config.use_last
    )
    fragment = SemanticFragment(
        "axi4_stream.link_semantics",
        constraints=(
            SemanticConstraint(
                "axi4_stream.byte_types",
                "effective TKEEP and TSTRB classify each lane as data, position, or null",
                ConstraintScope.EVENT,
                targets=("T",),
            ),
            SemanticConstraint(
                "axi4_stream.packet_identity",
                "a packet is identified by one TID and TDEST pair until TLAST",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("TID", "TDEST", "TLAST"),
            ),
            SemanticConstraint(
                "axi4_stream.interleaving",
                "transfers from distinct TID and TDEST streams may interleave",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("TID", "TDEST"),
            ),
            SemanticConstraint(
                "axi4_stream.transfer_order",
                "accepted transfers retain their observed order",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("T",),
            ),
        ),
        resources=(
            ResourceDecl(
                "axi4_stream.open_packets",
                ConstraintScope.LINK,
                description="TID/TDEST streams with a transfer awaiting TLAST",
                acquired_by=("T[last=False] starting a stream",),
                released_by=("T[last=True] for that stream", "reset"),
            ),
        ) if config.use_last else (),
        sources=("Arm IHI 0051B chapters 2-4",),
    )
    return LinkProtocol.define(
        "axi4_stream",
        family=AXI4_STREAM_FAMILY,
        roles=frozenset(("transmitter", "receiver")),
        channels={"T": channel},
        fragments=(fragment,),
        parameters={
            "data_width": config.data_width,
            "id_width": config.id_width,
            "dest_width": config.dest_width,
            "user_width": config.user_width,
            "use_keep": config.use_keep,
            "use_strb": config.use_strb,
            "use_last": config.use_last,
        },
        monitors={packet_monitor.name: packet_monitor},
    )


def build_axi4_stream_continuous_profile(
    config: Axi4StreamConfig | None = None,
) -> LinkProtocol:
    """Restrict AXI4-Stream to the specification's Continuous_Packets profile."""

    config = config or Axi4StreamConfig()
    if not config.use_last:
        raise ValueError("continuous packets require explicit TLAST")
    if config.use_strb:
        raise ValueError("continuous packets do not support TSTRB position bytes")
    base = build_axi4_stream_link(config)
    monitor = Axi4StreamContinuousMonitor(
        "axi4_stream.continuous",
        config.bytes_per_transfer,
        bool(config.id_width),
        bool(config.dest_width),
    )
    fragment = SemanticFragment(
        "axi4_stream.continuous_semantics",
        constraints=(
            SemanticConstraint(
                "axi4_stream.continuous.no_interleave",
                "TID and TDEST remain fixed between packet start and TLAST",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("TID", "TDEST", "TLAST"),
            ),
            SemanticConstraint(
                "axi4_stream.continuous.packed_bytes",
                "non-final transfers have no null bytes and final null bytes form an upper suffix",
                ConstraintScope.LINK,
                targets=("TKEEP", "TLAST"),
            ),
        ),
        sources=("Arm IHI 0051B 3.3",),
    )
    return base.refine(
        "axi4_stream_continuous",
        fragment,
        monitors={monitor.name: monitor},
    )
