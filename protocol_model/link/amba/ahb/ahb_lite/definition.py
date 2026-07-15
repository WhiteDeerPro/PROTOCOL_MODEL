"""AHB-Lite transaction schemas, burst sequencing, and in-order completion."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

from protocol_model.link import ChannelProtocol, EventField, EventSchema, LinkProtocol
from protocol_model.patterns import InOrderCompletionMonitor
from protocol_model.semantics import (
    BitVectorDomain,
    CanonicalEvent,
    ConstantDomain,
    ConstraintKind,
    ConstraintScope,
    EnumDomain,
    EventConstraint,
    EventOffer,
    ObligationDecl,
    ResourceDecl,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)


from .. import AHB_FAMILY

AHB_BURSTS = (
    "SINGLE",
    "INCR",
    "WRAP4",
    "INCR4",
    "WRAP8",
    "INCR8",
    "WRAP16",
    "INCR16",
)
_FIXED_BEATS = {
    "WRAP4": 4,
    "INCR4": 4,
    "WRAP8": 8,
    "INCR8": 8,
    "WRAP16": 16,
    "INCR16": 16,
}


@dataclass(frozen=True)
class AhbLiteConfig:
    address_width: int = 32
    data_width: int = 32

    def __post_init__(self) -> None:
        if self.address_width <= 0:
            raise ValueError("AHB address width must be positive")
        if self.data_width not in (8, 16, 32, 64, 128, 256, 512, 1024):
            raise ValueError("unsupported AHB data width")

    @property
    def bytes_per_transfer(self) -> int:
        return self.data_width // 8

    @property
    def maximum_size_encoding(self) -> int:
        return int(log2(self.bytes_per_transfer))


def _aligned(event: CanonicalEvent) -> bool:
    return int(event.payload["addr"]) % (1 << int(event.payload["size"])) == 0


def _single_is_nonseq(event: CanonicalEvent) -> bool:
    return event.payload["burst"] != "SINGLE" or event.payload["trans"] == "NONSEQ"


def _fixed_increment_does_not_cross_1kb(event: CanonicalEvent) -> bool:
    burst = str(event.payload["burst"])
    if not burst.startswith("INCR") or burst == "INCR":
        return True
    beats = _FIXED_BEATS[burst]
    start = int(event.payload["addr"])
    final = start + beats * (1 << int(event.payload["size"])) - 1
    return start // 1024 == final // 1024


def _common_request_fields(config: AhbLiteConfig) -> dict[str, EventField]:
    return {
        "addr": EventField("addr", BitVectorDomain(config.address_width)),
        "size": EventField(
            "size", EnumDomain(tuple(range(config.maximum_size_encoding + 1)))
        ),
        "burst": EventField("burst", EnumDomain(AHB_BURSTS)),
        "trans": EventField("trans", EnumDomain(("NONSEQ", "SEQ"))),
        "prot": EventField("prot", BitVectorDomain(4)),
        "lock": EventField("lock", EnumDomain((False, True))),
    }


def _request_constraints() -> tuple[EventConstraint, ...]:
    return (
        EventConstraint(
            "transfer_alignment",
            _aligned,
            "AHB transfer address must align to HSIZE",
        ),
        EventConstraint(
            "single_nonseq",
            _single_is_nonseq,
            "a SINGLE transfer must use NONSEQ",
        ),
        EventConstraint(
            "one_kb_boundary",
            _fixed_increment_does_not_cross_1kb,
            "fixed incrementing burst crosses a 1KB boundary",
        ),
    )


def _read_schema(config: AhbLiteConfig) -> EventSchema:
    return EventSchema(
        "READ",
        _common_request_fields(config),
        ConstantDomain(None),
        _request_constraints(),
    )


def _write_schema(config: AhbLiteConfig) -> EventSchema:
    fields = _common_request_fields(config)
    return EventSchema(
        "WRITE",
        fields,
        ConstantDomain(None),
        _request_constraints(),
    )


def _write_data_schema(config: AhbLiteConfig) -> EventSchema:
    fields = {"data": EventField("data", BitVectorDomain(config.data_width))}
    return EventSchema(
        "WRITE_DATA",
        fields,
        ConstantDomain(None),
    )


def _read_response_schema(config: AhbLiteConfig) -> EventSchema:
    return EventSchema(
        "READ_RESPONSE",
        {
            "data": EventField("data", BitVectorDomain(config.data_width)),
            "resp": EventField("resp", EnumDomain(("OKAY", "ERROR"))),
        },
        ConstantDomain(None),
    )


def _write_response_schema() -> EventSchema:
    return EventSchema(
        "WRITE_RESPONSE",
        {"resp": EventField("resp", EnumDomain(("OKAY", "ERROR")))},
        ConstantDomain(None),
    )


@dataclass(frozen=True)
class AhbBurstContext:
    request_kind: str
    burst: str
    size: int
    prot: int
    lock: bool
    start_address: int
    previous_address: int
    beat_index: int
    previous_index: int


@dataclass(frozen=True)
class AhbBurstState:
    active: AhbBurstContext | None = None


@dataclass(frozen=True)
class AhbBurstMonitor(
    SemanticComponent[CanonicalEvent, AhbBurstState, object]
):
    name: str = "ahb.burst"

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> AhbBurstState:
        return AhbBurstState()

    def is_quiescent(self, state: AhbBurstState) -> bool:
        return state.active is None or state.active.burst == "INCR"

    def event_offers(self, _state: AhbBurstState) -> tuple[EventOffer, ...]:
        return tuple(EventOffer.unconstrained(kind) for kind in self.event_kinds)

    def _fault(
        self, state: AhbBurstState, rule: str, reason: str
    ) -> SemanticStep[AhbBurstState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    @staticmethod
    def _next_address(context: AhbBurstContext) -> int:
        width = 1 << context.size
        next_linear = context.previous_address + width
        if context.burst.startswith("WRAP"):
            span = _FIXED_BEATS[context.burst] * width
            lower = (context.start_address // span) * span
            return lower + ((next_linear - lower) % span)
        return next_linear

    def step(
        self, state: AhbBurstState, event: CanonicalEvent
    ) -> SemanticStep[AhbBurstState, object]:
        if event.kind in {"READ_RESPONSE", "WRITE_RESPONSE"}:
            if event.payload["resp"] == "ERROR":
                return SemanticStep(AhbBurstState())
            return SemanticStep(state)
        if event.kind not in {"READ", "WRITE"}:
            return self._fault(state, "alphabet", f"unexpected event {event.kind!r}")
        if event.trace_index is None:
            return self._fault(
                state, "trace_index", "AHB requests must be normalized by a LinkSession"
            )
        trans = str(event.payload["trans"])
        burst = str(event.payload["burst"])
        if trans == "NONSEQ":
            if burst == "SINGLE":
                return SemanticStep(AhbBurstState())
            context = AhbBurstContext(
                event.kind,
                burst,
                int(event.payload["size"]),
                int(event.payload["prot"]),
                bool(event.payload["lock"]),
                int(event.payload["addr"]),
                int(event.payload["addr"]),
                1,
                event.trace_index,
            )
            return SemanticStep(AhbBurstState(context))

        context = state.active
        if context is None:
            return self._fault(
                state, "orphan_seq", "SEQ transfer has no active burst"
            )
        expected = self._next_address(context)
        observed = int(event.payload["addr"])
        if observed != expected:
            return self._fault(
                state,
                "address_sequence",
                f"burst beat requires address 0x{expected:x}, got 0x{observed:x}",
            )
        unchanged = (
            event.kind == context.request_kind
            and burst == context.burst
            and int(event.payload["size"]) == context.size
            and int(event.payload["prot"]) == context.prot
            and bool(event.payload["lock"]) == context.lock
        )
        if not unchanged:
            return self._fault(
                state,
                "control_stability",
                "direction, HBURST, HSIZE, HPROT, and HMASTLOCK must remain fixed within a burst",
            )
        if observed // 1024 != context.start_address // 1024:
            return self._fault(
                state, "one_kb_boundary", "incrementing burst crossed a 1KB boundary"
            )
        beat_index = context.beat_index + 1
        fixed_beats = _FIXED_BEATS.get(context.burst)
        next_context = None if fixed_beats == beat_index else AhbBurstContext(
            context.request_kind,
            context.burst,
            context.size,
            context.prot,
            context.lock,
            context.start_address,
            observed,
            beat_index,
            event.trace_index,
        )
        return SemanticStep(
            AhbBurstState(next_context),
            causal_predecessors=(context.previous_index,),
        )


@dataclass(frozen=True)
class AhbWriteDataState:
    request_index: int | None = None
    data_index: int | None = None
    address: int = 0
    size: int = 0


@dataclass(frozen=True)
class AhbWriteDataMonitor(
    SemanticComponent[CanonicalEvent, AhbWriteDataState, object]
):
    name: str

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("WRITE", "WRITE_DATA", "WRITE_RESPONSE"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> AhbWriteDataState:
        return AhbWriteDataState()

    def is_quiescent(self, state: AhbWriteDataState) -> bool:
        return state.request_index is None

    def event_offers(self, state: AhbWriteDataState) -> tuple[EventOffer, ...]:
        if state.request_index is None:
            return (EventOffer.unconstrained("WRITE"),)
        if state.data_index is None:
            return (EventOffer.unconstrained("WRITE_DATA"),)
        return (EventOffer.unconstrained("WRITE_RESPONSE"),)

    def _fault(
        self, state: AhbWriteDataState, rule: str, reason: str
    ) -> SemanticStep[AhbWriteDataState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    def step(
        self, state: AhbWriteDataState, event: CanonicalEvent
    ) -> SemanticStep[AhbWriteDataState, object]:
        if event.trace_index is None:
            return self._fault(
                state, "trace_index", "AHB write events require LinkSession indices"
            )
        if event.kind == "WRITE":
            if state.request_index is not None:
                return self._fault(
                    state, "overlap", "a second write address preceded write-data completion"
                )
            return SemanticStep(
                AhbWriteDataState(
                    event.trace_index,
                    None,
                    int(event.payload["addr"]),
                    int(event.payload["size"]),
                )
            )
        if event.kind == "WRITE_DATA":
            if state.request_index is None:
                return self._fault(
                    state, "orphan_data", "WRITE_DATA has no pending write address"
                )
            if state.data_index is not None:
                return self._fault(
                    state, "duplicate_data", "pending write already has WRITE_DATA"
                )
            return SemanticStep(
                AhbWriteDataState(
                    state.request_index,
                    event.trace_index,
                    state.address,
                    state.size,
                ),
                causal_predecessors=(state.request_index,),
            )
        if event.kind == "WRITE_RESPONSE":
            if state.request_index is None or state.data_index is None:
                return self._fault(
                    state,
                    "response_before_data",
                    "WRITE_RESPONSE requires the pending transfer WRITE_DATA",
                )
            return SemanticStep(
                AhbWriteDataState(),
                causal_predecessors=(state.data_index,),
            )
        return self._fault(state, "alphabet", f"unexpected event {event.kind!r}")


def build_ahb_lite_link(config: AhbLiteConfig | None = None) -> LinkProtocol:
    config = config or AhbLiteConfig()
    channels = {
        "READ": ChannelProtocol(
            "READ", "manager", "subordinate", _read_schema(config)
        ),
        "WRITE": ChannelProtocol(
            "WRITE", "manager", "subordinate", _write_schema(config)
        ),
        "WRITE_DATA": ChannelProtocol(
            "WRITE_DATA", "manager", "subordinate", _write_data_schema(config)
        ),
        "READ_RESPONSE": ChannelProtocol(
            "READ_RESPONSE",
            "subordinate",
            "manager",
            _read_response_schema(config),
        ),
        "WRITE_RESPONSE": ChannelProtocol(
            "WRITE_RESPONSE",
            "subordinate",
            "manager",
            _write_response_schema(),
        ),
    }
    completion = InOrderCompletionMonitor(
        "ahb.transfer",
        {"READ": "READ_RESPONSE", "WRITE": "WRITE_RESPONSE"},
        "ahb.pending_transfer",
        1,
    )
    burst = AhbBurstMonitor()
    write_data = AhbWriteDataMonitor("ahb.write_data")
    fragment = SemanticFragment(
        "ahb.core_link_semantics",
        constraints=(
            SemanticConstraint(
                "ahb.transfer_geometry",
                "HADDR aligns to HSIZE and HSIZE does not exceed the data bus",
                ConstraintScope.EVENT,
                targets=("READ", "WRITE"),
            ),
            SemanticConstraint(
                "ahb.in_order_completion",
                "the sole data phase completes the oldest accepted address phase",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("READ", "WRITE", "WRITE_DATA", "READ_RESPONSE", "WRITE_RESPONSE"),
            ),
            SemanticConstraint(
                "ahb.burst_sequence",
                "NONSEQ starts a burst and SEQ retains control while advancing or wrapping the address",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("READ", "WRITE"),
            ),
            SemanticConstraint(
                "ahb.one_kb_boundary",
                "incrementing bursts remain within one 1KB decode region",
                ConstraintScope.LINK,
                targets=("HADDR", "HBURST", "HSIZE"),
            ),
            SemanticConstraint(
                "ahb.write_data_phase",
                "WRITE_DATA follows its write address and precedes WRITE_RESPONSE",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("WRITE", "WRITE_DATA", "WRITE_RESPONSE"),
            ),
        ),
        resources=(
            ResourceDecl(
                "ahb.pending_transfer",
                ConstraintScope.LINK,
                capacity=1,
                description="accepted address phase awaiting its data-phase completion",
                acquired_by=("READ or WRITE",),
                released_by=("matching response", "reset"),
            ),
        ),
        obligations=(
            ObligationDecl(
                "ahb.read_completion",
                ConstraintScope.LINK,
                "READ",
                "READ_RESPONSE",
                "a read address phase receives one in-order data-phase response",
            ),
            ObligationDecl(
                "ahb.write_completion",
                ConstraintScope.LINK,
                "WRITE",
                "WRITE_RESPONSE",
                "a write address/data transfer receives one in-order response",
            ),
        ),
        sources=("Arm IHI 0033C chapters 3, 5, and 6",),
    )
    return LinkProtocol.define(
        "ahb_lite",
        family=AHB_FAMILY,
        roles=frozenset(("manager", "subordinate")),
        channels=channels,
        fragments=(fragment,),
        parameters={
            "address_width": config.address_width,
            "data_width": config.data_width,
            "revision": "AHB-Lite",
        },
        monitors={
            completion.name: completion,
            burst.name: burst,
            write_data.name: write_data,
        },
    )
