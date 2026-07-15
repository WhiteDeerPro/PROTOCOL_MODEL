"""Canonical-event AXI4 LinkProtocol definitions."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

from protocol_model.link import ChannelProtocol, EventField, EventSchema, LinkProtocol
from protocol_model.patterns import CardinalityMonitor
from protocol_model.semantics import (
    BitVectorDomain,
    ConstraintKind,
    ConstraintScope,
    EnumDomain,
    EventConstraint,
    ObligationDecl,
    ResourceDecl,
    SemanticConstraint,
    SemanticFragment,
)

from .burst import (
    byte_lane_mask,
    exclusive_length_is_legal,
    exclusive_size_is_legal,
    exclusive_start_is_aligned,
    fixed_length_is_legal,
    stays_in_address_space,
    stays_in_4kb,
    write_strobe_violation,
    wrap_length_is_legal,
    wrap_start_is_aligned,
)
from .exclusive import Axi4ExclusiveMonitor
from .write import Axi4WriteMonitor


AXI4_FAMILY = "amba.axi4"


@dataclass(frozen=True)
class Axi4Config:
    address_width: int = 32
    data_width: int = 64
    id_width: int = 4

    def __post_init__(self) -> None:
        if self.address_width <= 0 or self.id_width <= 0:
            raise ValueError("AXI address and ID widths must be positive")
        if (
            self.data_width < 8
            or self.data_width > 1024
            or self.data_width & (self.data_width - 1)
        ):
            raise ValueError(
                "AXI data width must be a power of two between 8 and 1024 bits"
            )

    @property
    def bytes_per_beat(self) -> int:
        return self.data_width // 8

    @property
    def maximum_size_encoding(self) -> int:
        return int(log2(self.bytes_per_beat))


def _address_schema(name: str, config: Axi4Config) -> EventSchema:
    fields = {
        "addr": EventField("addr", BitVectorDomain(config.address_width)),
        "len": EventField("len", BitVectorDomain(8)),
        "size": EventField(
            "size", EnumDomain(tuple(range(config.maximum_size_encoding + 1)))
        ),
        "burst": EventField("burst", EnumDomain(("FIXED", "INCR", "WRAP"))),
        "lock": EventField("lock", BitVectorDomain(1)),
        "cache": EventField("cache", BitVectorDomain(4)),
        "prot": EventField("prot", BitVectorDomain(3)),
        "qos": EventField("qos", BitVectorDomain(4)),
        "region": EventField("region", BitVectorDomain(4)),
    }
    return EventSchema(
        name,
        fields,
        BitVectorDomain(config.id_width),
        (
            EventConstraint(
                "wrap_length",
                wrap_length_is_legal,
                "WRAP burst length must be 2, 4, 8, or 16 transfers",
            ),
            EventConstraint(
                "fixed_length",
                fixed_length_is_legal,
                "FIXED burst length must not exceed 16 transfers",
            ),
            EventConstraint(
                "wrap_alignment",
                wrap_start_is_aligned,
                "WRAP start address must align to the transfer size",
            ),
            EventConstraint(
                "four_kb_boundary",
                stays_in_4kb,
                "burst crosses a 4KB address boundary",
            ),
            EventConstraint(
                "address_space",
                lambda event: stays_in_address_space(
                    event, address_width=config.address_width
                ),
                "burst transfer container exceeds the AxADDR address space",
            ),
            EventConstraint(
                "exclusive_length",
                exclusive_length_is_legal,
                "exclusive burst length must not exceed 16 transfers",
            ),
            EventConstraint(
                "exclusive_size",
                exclusive_size_is_legal,
                "exclusive transaction must transfer a power-of-two total no greater than 128 bytes",
            ),
            EventConstraint(
                "exclusive_alignment",
                exclusive_start_is_aligned,
                "exclusive address must align to the total transaction size",
            ),
        ),
    )


def _read_data_schema(config: Axi4Config) -> EventSchema:
    return EventSchema(
        "R",
        {
            "data": EventField("data", BitVectorDomain(config.data_width)),
            "resp": EventField(
                "resp", EnumDomain(("OKAY", "EXOKAY", "SLVERR", "DECERR"))
            ),
            "last": EventField("last", EnumDomain((False, True))),
        },
        BitVectorDomain(config.id_width),
    )


def _write_data_schema(config: Axi4Config) -> EventSchema:
    return EventSchema(
        "W",
        {
            "data": EventField("data", BitVectorDomain(config.data_width)),
            "strb": EventField("strb", BitVectorDomain(config.bytes_per_beat)),
            "last": EventField("last", EnumDomain((False, True))),
        },
    )


def _write_response_schema(config: Axi4Config) -> EventSchema:
    return EventSchema(
        "B",
        {
            "resp": EventField(
                "resp", EnumDomain(("OKAY", "EXOKAY", "SLVERR", "DECERR"))
            )
        },
        BitVectorDomain(config.id_width),
    )


def _exclusive_read_fragment() -> SemanticFragment:
    return SemanticFragment(
        "axi4.exclusive.read_semantics",
        constraints=(
            SemanticConstraint(
                "axi4.exclusive.read_geometry",
                "exclusive reads obey their length, total-size, and alignment restrictions",
                ConstraintScope.EVENT,
                targets=("AR",),
            ),
            SemanticConstraint(
                "axi4.exclusive.read_response",
                "normal reads do not receive EXOKAY and one exclusive read does not mix OKAY with EXOKAY",
                ConstraintScope.LINK,
                targets=("AR", "R"),
            ),
        ),
        resources=(
            ResourceDecl(
                "axi4.exclusive.reservations",
                ConstraintScope.LINK,
                description="completed exclusive reads that can make one matching write eligible for EXOKAY",
                acquired_by=("R[last=True, resp=EXOKAY]",),
                released_by=(
                    "matching AW[lock=1]",
                    "later same-ID AR[lock=1]",
                    "reset",
                ),
            ),
        ),
    )


def _exclusive_write_fragment() -> SemanticFragment:
    return SemanticFragment(
        "axi4.exclusive.write_semantics",
        constraints=(
            SemanticConstraint(
                "axi4.exclusive.write_geometry",
                "exclusive writes obey their length, total-size, and alignment restrictions",
                ConstraintScope.EVENT,
                targets=("AW",),
            ),
            SemanticConstraint(
                "axi4.exclusive.sequence",
                "an exclusive write waits for a pending same-ID exclusive read; matching completed attributes determine success eligibility",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AR", "R", "AW"),
            ),
            SemanticConstraint(
                "axi4.exclusive.write_response",
                "EXOKAY is returned only to an exclusive write eligible from a matching completed exclusive read",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AR", "R", "AW", "B"),
            ),
        ),
    )


def build_axi4_read_link(config: Axi4Config | None = None) -> LinkProtocol:
    """Build the minimal executable AXI4 read path: AR/R and read obligations."""

    config = config or Axi4Config()
    channels = {
        "AR": ChannelProtocol(
            "AR", "manager", "subordinate", _address_schema("AR", config)
        ),
        "R": ChannelProtocol(
            "R", "subordinate", "manager", _read_data_schema(config)
        ),
    }
    read_monitor = CardinalityMonitor(
        "axi4.read",
        "AR",
        "R",
        count_of=lambda event: int(event.payload["len"]) + 1,
        final_field="last",
        resource_name="axi4.read.pending_transactions",
    )
    exclusive_monitor = Axi4ExclusiveMonitor()
    fragment = SemanticFragment(
        "axi4.read.semantics",
        constraints=(
            SemanticConstraint(
                "axi4.read.burst_geometry",
                "AR length, size, burst type, alignment, and 4KB rules hold",
                ConstraintScope.EVENT,
                targets=("AR",),
            ),
            SemanticConstraint(
                "axi4.read.beat_count",
                "each AR creates exactly ARLEN plus one R beats",
                ConstraintScope.LINK,
                targets=("AR", "R"),
            ),
            SemanticConstraint(
                "axi4.read.last",
                "RLAST is asserted exactly on the final required R beat",
                ConstraintScope.LINK,
                targets=("R",),
            ),
            SemanticConstraint(
                "axi4.read.id_order",
                "R beats consume the oldest pending read with the same ID",
                ConstraintScope.LINK,
                targets=("AR", "R"),
            ),
            SemanticConstraint(
                "axi4.read.cross_id_interleave",
                "R beats for different IDs may be selected independently",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AR", "R"),
            ),
        ),
        obligations=(
            ObligationDecl(
                "axi4.read.response",
                ConstraintScope.LINK,
                "AR",
                "R[last=True]",
                "an accepted read address is completed by its final read-data beat",
            ),
        ),
        resources=(
            ResourceDecl(
                "axi4.read.pending_transactions",
                ConstraintScope.LINK,
                description="accepted AR transactions awaiting their final R beat",
                acquired_by=("AR",),
                released_by=("R[last=True]", "reset"),
            ),
        ),
    )
    return LinkProtocol.define(
        "axi4_read",
        family=AXI4_FAMILY,
        roles=frozenset(("manager", "subordinate")),
        channels=channels,
        fragments=(fragment, _exclusive_read_fragment()),
        parameters={
            "address_width": config.address_width,
            "data_width": config.data_width,
            "id_width": config.id_width,
        },
        monitors={
            read_monitor.name: read_monitor,
            exclusive_monitor.name: exclusive_monitor,
        },
    )


def build_axi4_link(config: Axi4Config | None = None) -> LinkProtocol:
    """Build the current five-channel AXI4 canonical-event model."""

    config = config or Axi4Config()
    read = build_axi4_read_link(config)
    channels = {
        "AW": ChannelProtocol(
            "AW", "manager", "subordinate", _address_schema("AW", config)
        ),
        "W": ChannelProtocol(
            "W", "manager", "subordinate", _write_data_schema(config)
        ),
        "B": ChannelProtocol(
            "B", "subordinate", "manager", _write_response_schema(config)
        ),
        **read.channels,
    }
    write_monitor = Axi4WriteMonitor(
        "axi4.write",
        count_of=lambda event: int(event.payload["len"]) + 1,
        data_rule=lambda address, index, data: write_strobe_violation(
            address, index, data, bus_bytes=config.bytes_per_beat
        ),
        data_offer=lambda address, index: {
            "strb": byte_lane_mask(
                address, index, bus_bytes=config.bytes_per_beat
            )
        },
        data_rule_name="byte_lanes",
    )
    write_fragment = SemanticFragment(
        "axi4.write.semantics",
        constraints=(
            SemanticConstraint(
                "axi4.write.burst_geometry",
                "AW length, size, burst type, alignment, and 4KB rules hold",
                ConstraintScope.EVENT,
                targets=("AW",),
            ),
            SemanticConstraint(
                "axi4.write.fifo_join",
                "ID-less W bursts join AW descriptors in acceptance order",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AW", "W"),
            ),
            SemanticConstraint(
                "axi4.write.beat_count",
                "each joined W burst contains exactly AWLEN plus one beats",
                ConstraintScope.LINK,
                targets=("AW", "W"),
            ),
            SemanticConstraint(
                "axi4.write.last",
                "WLAST is asserted exactly on the final required W beat",
                ConstraintScope.LINK,
                targets=("W",),
            ),
            SemanticConstraint(
                "axi4.write.byte_lanes",
                "WSTRB does not select byte lanes outside the addressed transfer",
                ConstraintScope.LINK,
                targets=("AW", "W"),
            ),
            SemanticConstraint(
                "axi4.write.response",
                "B consumes the oldest joined write with the same ID",
                ConstraintScope.LINK,
                targets=("AW", "W", "B"),
            ),
        ),
        resources=(
            ResourceDecl(
                "axi4.write.assembling_data",
                ConstraintScope.LINK,
                description="a partially observed W burst awaiting WLAST",
                acquired_by=("first W[last=False] of burst",),
                released_by=("W[last=True]", "reset"),
            ),
            ResourceDecl(
                "axi4.write.pending_descriptors",
                ConstraintScope.LINK,
                description="accepted AW descriptors awaiting a FIFO-matched W burst",
                acquired_by=("AW without available complete W burst",),
                released_by=("AW/W FIFO join", "reset"),
            ),
            ResourceDecl(
                "axi4.write.pending_data_bursts",
                ConstraintScope.LINK,
                description="complete W bursts observed before their FIFO-matched AW",
                acquired_by=("W[last=True] without available AW",),
                released_by=("AW/W FIFO join", "reset"),
            ),
            ResourceDecl(
                "axi4.write.pending_completions",
                ConstraintScope.LINK,
                description="joined AW/W transactions awaiting B",
                acquired_by=("AW/W FIFO join",),
                released_by=("B", "reset"),
            ),
        ),
        obligations=(
            ObligationDecl(
                "axi4.write.completion",
                ConstraintScope.LINK,
                "AW + W[last=True]",
                "B",
                "a FIFO-joined write transaction is completed by B",
            ),
        ),
    )
    return LinkProtocol.define(
        "axi4",
        family=AXI4_FAMILY,
        roles=read.roles,
        channels=channels,
        fragments=(read.semantics, write_fragment, _exclusive_write_fragment()),
        parameters=read.parameters,
        monitors={
            **read.monitors,
            write_monitor.name: write_monitor,
        },
    )
