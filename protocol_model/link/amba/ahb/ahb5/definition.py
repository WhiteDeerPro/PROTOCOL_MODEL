"""AHB5 interface-property profile derived from the AHB-Lite transaction core."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import ChannelProtocol, EventField, EventSchema, LinkProtocol
from protocol_model.semantics import (
    BitVectorDomain,
    CanonicalEvent,
    ConstraintKind,
    ConstraintScope,
    EnumDomain,
    EventConstraint,
    EventOffer,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from .. import AHB_FAMILY
from ..ahb_lite import AhbLiteConfig, build_ahb_lite_link


@dataclass(frozen=True)
class Ahb5Config:
    """Properties which change the canonical payload of one AHB5 interface.

    ``check_type`` is intentionally absent: parity is a raw-interface
    observation profile and needs check-signal observations, not transaction
    payload fields.
    """

    address_width: int = 32
    data_width: int = 32
    extended_memory_types: bool = False
    secure_transfers: bool = False
    write_strobes: bool = False
    exclusive_transfers: bool = False
    master_width: int = 4
    user_request_width: int = 0
    user_data_width: int = 0
    user_response_width: int = 0

    def __post_init__(self) -> None:
        AhbLiteConfig(self.address_width, self.data_width)
        if self.address_width > 64:
            raise ValueError("AHB5 address width must not exceed 64 bits")
        for name in (
            "extended_memory_types",
            "secure_transfers",
            "write_strobes",
            "exclusive_transfers",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"AHB5 {name} must be bool")
        for name in (
            "master_width",
            "user_request_width",
            "user_data_width",
            "user_response_width",
        ):
            width = getattr(self, name)
            if not isinstance(width, int) or isinstance(width, bool) or width < 0:
                raise ValueError(f"AHB5 {name} must be a non-negative integer")
        if self.exclusive_transfers and self.master_width == 0:
            raise ValueError("AHB5 exclusive transfers require a manager identifier")
        if self.master_width > 8:
            raise ValueError("this AHB5 link profile supports manager IDs up to 8 bits")
        if self.user_request_width > 128:
            raise ValueError("AHB5 request user width must not exceed 128 bits")
        if self.user_data_width > self.data_width // 2:
            raise ValueError("AHB5 data user width must not exceed DATA_WIDTH/2")
        if self.user_response_width > 16:
            raise ValueError("AHB5 response user width must not exceed 16 bits")

    @property
    def bytes_per_transfer(self) -> int:
        return self.data_width // 8


def _boolean_field(name: str, description: str) -> EventField:
    return EventField(name, EnumDomain((False, True)), description)


def _exclusive_request_shape(event: CanonicalEvent) -> bool:
    if not bool(event.payload["exclusive"]):
        return True
    return (
        event.payload["trans"] == "NONSEQ"
        and event.payload["burst"] in {"SINGLE", "INCR"}
    )


def _request_schema(base: EventSchema, config: Ahb5Config) -> EventSchema:
    fields = dict(base.fields)
    fields["prot"] = EventField(
        "prot",
        BitVectorDomain(7 if config.extended_memory_types else 4),
        "HPROT access and memory attributes",
    )
    constraints = list(base.constraints)
    if config.secure_transfers:
        fields["nonsecure"] = _boolean_field(
            "nonsecure", "HNONSEC security-domain indication"
        )
    if config.exclusive_transfers:
        fields["exclusive"] = _boolean_field(
            "exclusive", "HEXCL exclusive-transfer indication"
        )
        fields["master"] = EventField(
            "master",
            BitVectorDomain(config.master_width),
            "HMASTER manager or exclusive-thread identifier",
        )
        constraints.append(
            EventConstraint(
                "exclusive_single_beat",
                _exclusive_request_shape,
                "an AHB5 Exclusive transfer must be a single NONSEQ beat using SINGLE or INCR",
            )
        )
    if config.user_request_width:
        fields["auser"] = EventField(
            "auser",
            BitVectorDomain(config.user_request_width),
            "HAUSER request attribute",
        )
    return EventSchema(base.name, fields, base.key, tuple(constraints))


def _write_data_schema(base: EventSchema, config: Ahb5Config) -> EventSchema:
    fields = dict(base.fields)
    if config.write_strobes:
        fields["strb"] = EventField(
            "strb",
            BitVectorDomain(config.bytes_per_transfer),
            "HWSTRB sparse-write byte strobes",
        )
    if config.user_data_width:
        fields["wuser"] = EventField(
            "wuser",
            BitVectorDomain(config.user_data_width),
            "HWUSER write-data attribute",
        )
    return EventSchema(base.name, fields, base.key, base.constraints)


def _response_schema(
    base: EventSchema, config: Ahb5Config, *, read: bool
) -> EventSchema:
    fields = dict(base.fields)
    if config.exclusive_transfers:
        fields["exclusive_ok"] = _boolean_field(
            "exclusive_ok", "HEXOKAY exclusive transfer result"
        )
    if read and config.user_data_width:
        fields["ruser"] = EventField(
            "ruser",
            BitVectorDomain(config.user_data_width),
            "HRUSER read-data attribute",
        )
    if config.user_response_width:
        fields["buser"] = EventField(
            "buser",
            BitVectorDomain(config.user_response_width),
            "HBUSER transfer-response attribute",
        )
    return EventSchema(base.name, fields, base.key, base.constraints)


@dataclass(frozen=True)
class Ahb5ExclusivePending:
    response_kind: str
    exclusive: bool
    origin_index: int


@dataclass(frozen=True)
class Ahb5ExclusiveState:
    pending: Ahb5ExclusivePending | None = None


@dataclass(frozen=True)
class Ahb5ExclusiveSignalMonitor(
    SemanticComponent[CanonicalEvent, Ahb5ExclusiveState, object]
):
    """Check link-visible HEXCL/HEXOKAY response legality.

    Whether a successful Exclusive Write is still permitted by other writers
    belongs to the Exclusive Access Monitor at the memory/system boundary.
    """

    name: str = "ahb5.exclusive_signaling"

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> Ahb5ExclusiveState:
        return Ahb5ExclusiveState()

    def is_quiescent(self, state: Ahb5ExclusiveState) -> bool:
        return state.pending is None

    def event_offers(self, state: Ahb5ExclusiveState) -> tuple[EventOffer, ...]:
        if state.pending is None:
            return (EventOffer.unconstrained("READ"), EventOffer.unconstrained("WRITE"))
        return (EventOffer.unconstrained(state.pending.response_kind),)

    def _fault(
        self, state: Ahb5ExclusiveState, rule: str, reason: str
    ) -> SemanticStep[Ahb5ExclusiveState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    def step(
        self, state: Ahb5ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Ahb5ExclusiveState, object]:
        if event.trace_index is None:
            return self._fault(
                state, "trace_index", "AHB5 events require LinkSession indices"
            )
        if event.kind in {"READ", "WRITE"}:
            if state.pending is not None:
                return self._fault(
                    state, "overlap", "a transfer is already awaiting its data phase"
                )
            return SemanticStep(
                Ahb5ExclusiveState(
                    Ahb5ExclusivePending(
                        "READ_RESPONSE" if event.kind == "READ" else "WRITE_RESPONSE",
                        bool(event.payload["exclusive"]),
                        event.trace_index,
                    )
                )
            )
        pending = state.pending
        if pending is None:
            return self._fault(state, "orphan_response", "response has no address phase")
        if event.kind != pending.response_kind:
            return self._fault(
                state,
                "response_kind",
                f"pending transfer requires {pending.response_kind}, got {event.kind}",
            )
        exclusive_ok = bool(event.payload["exclusive_ok"])
        if exclusive_ok and not pending.exclusive:
            return self._fault(
                state,
                "nonexclusive_success",
                "HEXOKAY can only be asserted for an Exclusive transfer",
            )
        if exclusive_ok and event.payload["resp"] == "ERROR":
            return self._fault(
                state,
                "error_success",
                "HEXOKAY cannot be asserted with an ERROR response",
            )
        return SemanticStep(
            Ahb5ExclusiveState(), causal_predecessors=(pending.origin_index,)
        )


def build_ahb5_link(config: Ahb5Config | None = None) -> LinkProtocol:
    """Build an AHB5 link with selected Issue C interface properties."""

    config = config or Ahb5Config()
    base = build_ahb_lite_link(
        AhbLiteConfig(config.address_width, config.data_width)
    )
    channels = {}
    for name, channel in base.channels.items():
        if name in {"READ", "WRITE"}:
            event = _request_schema(channel.event, config)
        elif name == "WRITE_DATA":
            event = _write_data_schema(channel.event, config)
        elif name == "READ_RESPONSE":
            event = _response_schema(channel.event, config, read=True)
        else:
            event = _response_schema(channel.event, config, read=False)
        channels[name] = ChannelProtocol(
            name, channel.source_role, channel.destination_role, event
        )

    monitors = dict(base.monitors)
    if config.exclusive_transfers:
        exclusive = Ahb5ExclusiveSignalMonitor()
        monitors[exclusive.name] = exclusive

    feature_names = tuple(
        name
        for name, enabled in (
            ("extended memory types", config.extended_memory_types),
            ("secure transfers", config.secure_transfers),
            ("write strobes", config.write_strobes),
            ("exclusive signaling", config.exclusive_transfers),
            ("request user signaling", bool(config.user_request_width)),
            ("data user signaling", bool(config.user_data_width)),
            ("response user signaling", bool(config.user_response_width)),
        )
        if enabled
    )
    fragment = SemanticFragment(
        "ahb5.interface_properties",
        constraints=(
            SemanticConstraint(
                "ahb5.configured_payload",
                "configured AHB5 interface properties determine which address, data, and response fields are present",
                ConstraintScope.LINK,
                targets=("READ", "WRITE", "WRITE_DATA", "READ_RESPONSE", "WRITE_RESPONSE"),
            ),
            *(
                (
                    SemanticConstraint(
                        "ahb5.exclusive_response",
                        "HEXOKAY is asserted only for a successful Exclusive transfer with an OKAY response",
                        ConstraintScope.LINK,
                        kind=ConstraintKind.RELATION,
                        targets=("READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"),
                    ),
                )
                if config.exclusive_transfers
                else ()
            ),
        ),
        sources=(
            "Arm IHI 0033C sections 3.5, 3.9, 3.10, 10.3-10.4, and 11.1",
        ),
    )
    return LinkProtocol.define(
        "ahb5",
        family=AHB_FAMILY,
        roles=base.roles,
        channels=channels,
        fragments=(base.semantics, fragment),
        parameters={
            "revision": "AHB5 / IHI 0033C",
            "address_width": config.address_width,
            "data_width": config.data_width,
            "extended_memory_types": config.extended_memory_types,
            "secure_transfers": config.secure_transfers,
            "write_strobes": config.write_strobes,
            "exclusive_transfers": config.exclusive_transfers,
            "master_width": config.master_width,
            "user_request_width": config.user_request_width,
            "user_data_width": config.user_data_width,
            "user_response_width": config.user_response_width,
            "enabled_features": feature_names,
            "check_type": "none",
        },
        monitors=monitors,
    )
