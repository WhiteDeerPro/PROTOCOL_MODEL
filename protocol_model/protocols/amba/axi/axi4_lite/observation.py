"""AXI4-Lite ready/valid observation using the shared AXI lane lowering."""

from __future__ import annotations

from protocol_model.protocols.amba.axi.axi4.observation import (
    Axi4ObservationPolicy,
    Axi4ObservationSession,
)

from .definition import Axi4LiteConfig, build_axi4_lite_interface


class Axi4LiteObservationSession(Axi4ObservationSession):
    def __init__(
        self,
        config: Axi4LiteConfig | None = None,
        *,
        clock: str = "aclk",
        reset_lane: str = "reset",
        policy: Axi4ObservationPolicy | None = None,
    ) -> None:
        super().__init__(
            build_axi4_lite_interface(config),
            clock=clock,
            reset_lane=reset_lane,
            policy=policy,
        )
