"""First AXI4 lowering stage: parameters, roles, channel transfer spaces and gaps."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

from protocol_model.patterns import ClockedReadyValid, ResetEpoch
from protocol_model.semantics import (
    CardinalityObligation,
    CorrelatedCardinalityObligation,
)
from protocol_model.domains import (
    BitVectorDomain,
    ConstantDomain,
    EnumDomain,
    EventConstraint,
    EventSpace,
)
from protocol_model.protocols.spec import ChannelSpec, ProtocolRequirement, ProtocolSpec
from .burst import byte_lane_mask, write_strobe_violation


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
        if self.data_width % 8:
            raise ValueError("AXI data width must contain whole bytes")

    @property
    def bytes_per_data_beat(self) -> int:
        return self.data_width // 8

    @property
    def maximum_size_encoding(self) -> int:
        return int(log2(self.bytes_per_data_beat))


def _wrap_length_is_legal(event) -> bool:
    return event.payload["burst"] != "WRAP" or event.payload["len"] in {1, 3, 7, 15}


def _fixed_length_is_legal(event) -> bool:
    return event.payload["burst"] != "FIXED" or int(event.payload["len"]) <= 15


def _wrap_start_is_aligned(event) -> bool:
    return event.payload["burst"] != "WRAP" or (
        int(event.payload["addr"]) % (1 << int(event.payload["size"])) == 0
    )


def _stays_in_4kb(event) -> bool:
    address = int(event.payload["addr"])
    beats = int(event.payload["len"]) + 1
    bytes_per_beat = 1 << int(event.payload["size"])
    burst = event.payload["burst"]
    if burst == "FIXED":
        last = address + bytes_per_beat - 1
    elif burst == "WRAP":
        total = beats * bytes_per_beat
        boundary = (address // total) * total
        last = boundary + total - 1
    else:
        aligned = (address // bytes_per_beat) * bytes_per_beat
        last = aligned + beats * bytes_per_beat - 1
    return address // 4096 == last // 4096


def _address_space(kind: str, config: Axi4Config) -> EventSpace:
    return EventSpace(
        kind,
        BitVectorDomain(config.id_width),
        {
            "addr": BitVectorDomain(config.address_width),
            "len": BitVectorDomain(8),
            "size": EnumDomain(tuple(range(config.maximum_size_encoding + 1))),
            "burst": EnumDomain(("FIXED", "INCR", "WRAP")),
            "lock": BitVectorDomain(1),
            "cache": BitVectorDomain(4),
            "prot": BitVectorDomain(3),
            "qos": BitVectorDomain(4),
            "region": BitVectorDomain(4),
        },
        (
            EventConstraint(
                "wrap_length",
                _wrap_length_is_legal,
                "WRAP burst length must be 2, 4, 8, or 16 transfers",
            ),
            EventConstraint(
                "fixed_length",
                _fixed_length_is_legal,
                "FIXED burst length must not exceed 16 transfers",
            ),
            EventConstraint(
                "wrap_alignment",
                _wrap_start_is_aligned,
                "WRAP start address must align to the transfer size",
            ),
            EventConstraint(
                "four_kb_boundary",
                _stays_in_4kb,
                "burst crosses a 4KB address boundary",
            ),
        ),
    )


def _channel(
    name: str,
    source_role: str,
    destination_role: str,
    transfer: EventSpace,
) -> ChannelSpec:
    ready_valid = ClockedReadyValid(f"{name}.ready_valid", transfer, clock="aclk")
    return ChannelSpec(
        name,
        source_role,
        destination_role,
        transfer,
        ResetEpoch(
            f"{name}.reset_epoch",
            ready_valid,
            inactive=lambda sample: not sample.valid,
            inactive_reason=f"{name} VALID must be low while reset is asserted",
        ),
    )


def build_axi4_spec(config: Axi4Config | None = None) -> ProtocolSpec:
    config = config or Axi4Config()
    id_domain = BitVectorDomain(config.id_width)
    response = EnumDomain(("OKAY", "EXOKAY", "SLVERR", "DECERR"))
    channels = {
        "AW": _channel("AW", "manager", "subordinate", _address_space("AW_TRANSFER", config)),
        "W": _channel(
            "W",
            "manager",
            "subordinate",
            EventSpace(
                "W_TRANSFER",
                ConstantDomain(None),
                {
                    "data": BitVectorDomain(config.data_width),
                    "strb": BitVectorDomain(config.bytes_per_data_beat),
                    "last": EnumDomain((False, True)),
                },
            ),
        ),
        "B": _channel(
            "B",
            "subordinate",
            "manager",
            EventSpace("B_TRANSFER", id_domain, {"resp": response}),
        ),
        "AR": _channel("AR", "manager", "subordinate", _address_space("AR_TRANSFER", config)),
        "R": _channel(
            "R",
            "subordinate",
            "manager",
            EventSpace(
                "R_TRANSFER",
                id_domain,
                {
                    "data": BitVectorDomain(config.data_width),
                    "resp": response,
                    "last": EnumDomain((False, True)),
                },
            ),
        ),
    }
    requirements = (
        ProtocolRequirement("five_channels", "AW/W/B/AR/R roles and payload shapes", "ProtocolSpec", "implemented"),
        ProtocolRequirement("burst_geometry", "AxLEN/AxSIZE/AxBURST and 4KB rules", "EventConstraint", "implemented"),
        ProtocolRequirement("beat_address", "derive FIXED/INCR/WRAP address for every beat", "BurstAddress", "implemented"),
        ProtocolRequirement("write_byte_lanes", "WSTRB may assert only byte lanes selected by address and size", "ByteLaneMask", "implemented"),
        ProtocolRequirement("handshake", "transfer iff VALID and READY at a rising edge", "ClockedReadyValid", "implemented"),
        ProtocolRequirement("stall_stability", "VALID and payload remain stable while blocked", "ClockedReadyValid", "implemented"),
        ProtocolRequirement("reset", "VALID low during reset and per-epoch state isolation", "ResetEpoch", "implemented"),
        ProtocolRequirement("response_valid_dependency", "BVALID requires prior AW/W join; RVALID requires prior AR", "Axi4SignalSession", "implemented"),
        ProtocolRequirement("write_join", "accepted AW plus complete W burst creates one B obligation", "CorrelatedCardinalityObligation", "implemented"),
        ProtocolRequirement("write_data_match", "associate ID-less W bursts with AW order", "CorrelatedCardinalityObligation", "implemented"),
        ProtocolRequirement("write_beats", "AWLEN supplies the exact W beat count and final WLAST", "CorrelatedCardinalityObligation", "implemented"),
        ProtocolRequirement("read_beats", "AR creates ARLEN+1 R beat obligations with final RLAST", "CardinalityObligation", "implemented"),
        ProtocolRequirement("id_ordering", "responses with the same ID consume the oldest pending token", "KeyedFifoToken", "implemented"),
        ProtocolRequirement("cross_id_interleave", "commuting events may share one concurrent step", "DynamicCommutation", "implemented"),
        ProtocolRequirement("structural_no_comb_path", "no combinational input-to-output path", "StructuralEvidence", "missing"),
    )
    read_transactions = CardinalityObligation(
        "axi4.read_beats",
        channels["AR"].transfer,
        channels["R"].transfer,
        count_of=lambda event: int(event.payload["len"]) + 1,
        final_field="last",
    )
    write_transactions = CorrelatedCardinalityObligation(
        "axi4.write",
        channels["AW"].transfer,
        channels["W"].transfer,
        channels["B"].transfer,
        count_of=lambda event: int(event.payload["len"]) + 1,
        final_field="last",
        data_rule=lambda address, index, data: write_strobe_violation(
            address,
            index,
            data,
            bus_bytes=config.bytes_per_data_beat,
        ),
        data_overrides=lambda address, index, rng: {
            "strb": byte_lane_mask(
                address, index, bus_bytes=config.bytes_per_data_beat
            )
        },
    )
    return ProtocolSpec(
        "axi4",
        frozenset({"manager", "subordinate"}),
        channels,
        requirements,
        {
            "address_width": config.address_width,
            "data_width": config.data_width,
            "id_width": config.id_width,
        },
        {"read": read_transactions, "write": write_transactions},
    )
