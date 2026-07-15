"""APB4 SETUP/ACCESS observation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from .._common.observation import (
    ApbPhaseObservationSession,
    ApbPhaseObservationState,
    validate_boolean_signals,
)
from .definition import Apb4Config, build_apb4_link


@dataclass(frozen=True)
class Apb4Signals:
    psel: bool
    penable: bool
    pready: bool = True
    paddr: int = 0
    pwrite: bool = False
    pwdata: int = 0
    pstrb: int = 0
    pprot: int = 0
    prdata: int = 0
    pslverr: bool = False

    def __post_init__(self) -> None:
        validate_boolean_signals(
            self, ("psel", "penable", "pready", "pwrite", "pslverr")
        )


@dataclass(frozen=True)
class Apb4ObservationState(ApbPhaseObservationState):
    pass


class Apb4ObservationSession(ApbPhaseObservationSession):
    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        config: Apb4Config | None = None,
        clock: str = "pclk",
        lane: str = "APB",
        reset_lane: str = "reset",
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an APB4 protocol or config")
        protocol = protocol or build_apb4_link(config)
        if protocol.parameters.get("revision") != "APB4":
            raise ValueError("APB4 observation requires an APB4 protocol")
        self.pprot_present = bool(protocol.parameters["pprot_present"])
        self.pstrb_present = bool(protocol.parameters["pstrb_present"])

        def request_payload(signals: object) -> dict[str, object]:
            assert isinstance(signals, Apb4Signals)
            payload: dict[str, object] = {"addr": signals.paddr}
            if self.pprot_present:
                payload["prot"] = signals.pprot
            if signals.pwrite:
                payload["data"] = signals.pwdata
                if self.pstrb_present:
                    payload["strb"] = signals.pstrb
            return payload

        def completion_payload(
            signals: object, is_write: bool
        ) -> dict[str, object]:
            assert isinstance(signals, Apb4Signals)
            payload: dict[str, object] = {"error": signals.pslverr}
            if not is_write:
                payload["data"] = signals.prdata
            return payload

        def validate_sample(signals: object) -> tuple[str, str] | None:
            assert isinstance(signals, Apb4Signals)
            if not self.pprot_present and signals.pprot:
                return (
                    "absent_pprot",
                    "normalized PPROT must be zero when the signal is absent",
                )
            if not self.pstrb_present and signals.pstrb:
                return (
                    "absent_pstrb",
                    "normalized PSTRB must be zero when the signal is absent",
                )
            if (
                self.pstrb_present
                and signals.psel
                and not signals.pwrite
                and signals.pstrb
            ):
                return (
                    "read_strobe",
                    "PSTRB must be zero during an APB read transfer",
                )
            return None

        stable_signals = ["PADDR", "PWRITE", "PWDATA"]
        if self.pprot_present:
            stable_signals.append("PPROT")
        if self.pstrb_present:
            stable_signals.append("PSTRB")
        super().__init__(
            protocol,
            signal_type=Apb4Signals,
            state_type=Apb4ObservationState,
            request_payload=request_payload,
            completion_payload=completion_payload,
            validate_sample=validate_sample,
            stable_signals=tuple(stable_signals),
            completion_signals=("PRDATA", "PSLVERR"),
            source="Arm IHI 0024E sections 3.1-3.5 and 4.1",
            clock=clock,
            lane=lane,
            reset_lane=reset_lane,
        )
