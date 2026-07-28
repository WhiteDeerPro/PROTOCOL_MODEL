"""Atomic ready/valid observation for the ACE-Lite data profile."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import (
    Axi4ObservationPolicy,
    Axi4ObservationSession,
)

from .definition import AceLiteDataConfig, build_ace_lite_data_interface


class AceLiteDataObservationSession(Axi4ObservationSession):
    """Lower five normalized ACE-Lite lanes through the AXI observation core."""

    def __init__(
        self,
        protocol: InterfaceProtocol | None = None,
        *,
        config: AceLiteDataConfig | None = None,
        clock: str = "aclk",
        reset_lane: str = "reset",
        policy: Axi4ObservationPolicy | None = None,
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an ACE-Lite protocol or config")
        super().__init__(
            protocol or build_ace_lite_data_interface(config),
            clock=clock,
            reset_lane=reset_lane,
            policy=policy,
        )
