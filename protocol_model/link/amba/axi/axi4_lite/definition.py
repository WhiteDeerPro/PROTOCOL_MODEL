"""Native AXI4-Lite schemas and single-link transaction semantics."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import ChannelProtocol, EventField, EventSchema, LinkProtocol
from protocol_model.link.amba.byte_lanes import transfer_container_lane_mask
from protocol_model.link.amba.axi.axi4.write import Axi4WriteMonitor
from protocol_model.patterns import CardinalityMonitor
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


AXI4_LITE_FAMILY = "amba.axi4_lite"


@dataclass(frozen=True)
class Axi4LiteConfig:
    address_width: int = 32
    data_width: int = 32

    def __post_init__(self) -> None:
        if self.address_width <= 0:
            raise ValueError("AXI4-Lite address width must be positive")
        if self.data_width not in (32, 64):
            raise ValueError("AXI4-Lite data width must be 32 or 64 bits")

    @property
    def bytes_per_beat(self) -> int:
        return self.data_width // 8


def _address_schema(name: str, config: Axi4LiteConfig) -> EventSchema:
    return EventSchema(
        name,
        {
            "addr": EventField("addr", BitVectorDomain(config.address_width)),
            "prot": EventField("prot", BitVectorDomain(3)),
        },
        ConstantDomain(None),
    )


def _write_data_schema(config: Axi4LiteConfig) -> EventSchema:
    return EventSchema(
        "W",
        {
            "data": EventField("data", BitVectorDomain(config.data_width)),
            "strb": EventField("strb", BitVectorDomain(config.bytes_per_beat)),
        },
        ConstantDomain(None),
    )


def _response_domain() -> EnumDomain[str]:
    return EnumDomain(("OKAY", "SLVERR", "DECERR"))


def _write_strobe_violation(
    address, _index: int, data, *, bus_bytes: int
) -> str | None:
    allowed = transfer_container_lane_mask(
        int(address.payload["addr"]),
        transfer_width=bus_bytes,
        bus_bytes=bus_bytes,
    )
    observed = int(data.payload["strb"])
    if observed & ~allowed:
        return (
            f"WSTRB 0x{observed:x} selects lanes outside implicit full-width "
            f"AXI4-Lite mask 0x{allowed:x}"
        )
    return None


def _write_strobe_offer(address, _index: int, *, bus_bytes: int) -> dict[str, int]:
    return {
        "strb": transfer_container_lane_mask(
            int(address.payload["addr"]),
            transfer_width=bus_bytes,
            bus_bytes=bus_bytes,
        )
    }


def _write_response_schema() -> EventSchema:
    return EventSchema(
        "B",
        {"resp": EventField("resp", _response_domain())},
        ConstantDomain(None),
    )


def _read_data_schema(config: Axi4LiteConfig) -> EventSchema:
    return EventSchema(
        "R",
        {
            "data": EventField("data", BitVectorDomain(config.data_width)),
            "resp": EventField("resp", _response_domain()),
        },
        ConstantDomain(None),
    )


def build_axi4_lite_link(config: Axi4LiteConfig | None = None) -> LinkProtocol:
    """Build the native five-channel AXI4-Lite LinkProtocol.

    Burst attributes, IDs, LOCK/CACHE, and LAST are intentionally absent from
    the native schema. Their fixed AXI4 meanings are supplied only by the
    explicit AXI4 embedding.
    """

    config = config or Axi4LiteConfig()
    channels = {
        "AW": ChannelProtocol(
            "AW", "manager", "subordinate", _address_schema("AW", config)
        ),
        "W": ChannelProtocol(
            "W", "manager", "subordinate", _write_data_schema(config)
        ),
        "B": ChannelProtocol(
            "B", "subordinate", "manager", _write_response_schema()
        ),
        "AR": ChannelProtocol(
            "AR", "manager", "subordinate", _address_schema("AR", config)
        ),
        "R": ChannelProtocol(
            "R", "subordinate", "manager", _read_data_schema(config)
        ),
    }
    read_monitor = CardinalityMonitor(
        "axi4_lite.read",
        "AR",
        "R",
        count_of=lambda _event: 1,
        resource_name="axi4_lite.read.pending_transactions",
    )
    write_monitor = Axi4WriteMonitor(
        "axi4_lite.write",
        count_of=lambda _event: 1,
        data_rule=lambda address, index, data: _write_strobe_violation(
            address, index, data, bus_bytes=config.bytes_per_beat
        ),
        data_offer=lambda address, index: _write_strobe_offer(
            address, index, bus_bytes=config.bytes_per_beat
        ),
        final_field=None,
        data_rule_name="byte_lanes",
    )
    fragment = SemanticFragment(
        "axi4_lite.link_semantics",
        constraints=(
            SemanticConstraint(
                "axi4_lite.single_beat",
                "each address opens exactly one data transfer and one response",
                ConstraintScope.LINK,
                targets=("AW", "W", "B", "AR", "R"),
            ),
            SemanticConstraint(
                "axi4_lite.write_fifo_join",
                "ID-less AW and W transfers join in acceptance order, including W before AW",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AW", "W"),
            ),
            SemanticConstraint(
                "axi4_lite.in_order",
                "read and write responses consume their oldest pending transaction",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("AR", "R", "AW", "W", "B"),
            ),
            SemanticConstraint(
                "axi4_lite.response_set",
                "read and write responses are OKAY, SLVERR, or DECERR",
                ConstraintScope.EVENT,
                targets=("R", "B"),
            ),
            SemanticConstraint(
                "axi4_lite.write_byte_lanes",
                "WSTRB does not select byte lanes outside the full-width transfer container",
                ConstraintScope.LINK,
                targets=("AW", "W"),
            ),
        ),
        resources=(
            ResourceDecl(
                "axi4_lite.read.pending_transactions",
                ConstraintScope.LINK,
                description="accepted AR transfers awaiting R",
                acquired_by=("AR",),
                released_by=("R", "reset"),
            ),
            ResourceDecl(
                "axi4_lite.write.pending_descriptors",
                ConstraintScope.LINK,
                description="accepted AW transfers awaiting FIFO-matched W",
                acquired_by=("AW without available W",),
                released_by=("AW/W FIFO join", "reset"),
            ),
            ResourceDecl(
                "axi4_lite.write.pending_data_bursts",
                ConstraintScope.LINK,
                description="single W transfers observed before FIFO-matched AW",
                acquired_by=("W without available AW",),
                released_by=("AW/W FIFO join", "reset"),
            ),
            ResourceDecl(
                "axi4_lite.write.pending_completions",
                ConstraintScope.LINK,
                description="joined AW/W transactions awaiting B",
                acquired_by=("AW/W FIFO join",),
                released_by=("B", "reset"),
            ),
        ),
        obligations=(
            ObligationDecl(
                "axi4_lite.read.response",
                ConstraintScope.LINK,
                "AR",
                "R",
                "an accepted read address is completed by one read response",
            ),
            ObligationDecl(
                "axi4_lite.write.response",
                ConstraintScope.LINK,
                "AW + W",
                "B",
                "a FIFO-joined write is completed by one write response",
            ),
        ),
        sources=("Arm IHI 0022H B1",),
    )
    return LinkProtocol.define(
        "axi4_lite",
        family=AXI4_LITE_FAMILY,
        roles=frozenset(("manager", "subordinate")),
        channels=channels,
        fragments=(fragment,),
        parameters={
            "address_width": config.address_width,
            "data_width": config.data_width,
        },
        monitors={
            read_monitor.name: read_monitor,
            write_monitor.name: write_monitor,
        },
    )
