"""Elaborate a generic data-bearing ready/valid channel."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.domains import BitVectorDomain, ConstantDomain, EventSpace
from protocol_model.patterns import ClockedReadyValid, ResetEpoch
from protocol_model.protocols.spec import ChannelSpec, ProtocolRequirement, ProtocolSpec


@dataclass(frozen=True)
class ReadyValidConfig:
    data_width: int = 8
    clock: str = "clk"

    def __post_init__(self) -> None:
        if self.data_width <= 0:
            raise ValueError("ready-valid data width must be positive")
        if not self.clock:
            raise ValueError("ready-valid clock name must not be empty")


def build_ready_valid_spec(
    config: ReadyValidConfig | None = None,
) -> ProtocolSpec:
    config = config or ReadyValidConfig()
    transfer = EventSpace(
        "DATA_TRANSFER",
        ConstantDomain(None),
        {"data": BitVectorDomain(config.data_width)},
    )
    handshake = ClockedReadyValid(
        "data.ready_valid", transfer, clock=config.clock
    )
    channel = ChannelSpec(
        "DATA",
        "source",
        "sink",
        transfer,
        ResetEpoch(
            "data.reset_epoch",
            handshake,
            inactive=lambda sample: not sample.valid,
            inactive_reason="DATA VALID must be low while reset is asserted",
        ),
    )
    return ProtocolSpec(
        "ready_valid",
        frozenset({"source", "sink"}),
        {"DATA": channel},
        (
            ProtocolRequirement(
                "transfer",
                "a transfer occurs exactly when VALID and READY are sampled high",
                "ClockedReadyValid",
                "implemented",
            ),
            ProtocolRequirement(
                "stall_stability",
                "VALID and payload remain stable while READY is low",
                "ClockedReadyValid",
                "implemented",
            ),
            ProtocolRequirement(
                "reset",
                "VALID is low during reset and stalled state is cleared",
                "ResetEpoch",
                "implemented",
            ),
        ),
        {"data_width": config.data_width, "clock": config.clock},
    )
