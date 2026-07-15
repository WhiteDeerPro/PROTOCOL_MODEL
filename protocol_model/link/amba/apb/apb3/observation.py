"""APB3 SETUP/ACCESS observation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from .._common.observation import (
    ApbPhaseObservationSession,
    ApbPhaseObservationState,
    validate_boolean_signals,
)
from .definition import Apb3Config, build_apb3_link


@dataclass(frozen=True)
class Apb3Signals:
    psel: bool
    penable: bool
    pready: bool = True
    paddr: int = 0
    pwrite: bool = False
    pwdata: int = 0
    prdata: int = 0
    pslverr: bool = False

    def __post_init__(self) -> None:
        validate_boolean_signals(
            self, ("psel", "penable", "pready", "pwrite", "pslverr")
        )


@dataclass(frozen=True)
class Apb3ObservationState(ApbPhaseObservationState):
    pass


def _request_payload(signals: object) -> dict[str, object]:
    assert isinstance(signals, Apb3Signals)
    payload: dict[str, object] = {"addr": signals.paddr}
    if signals.pwrite:
        payload["data"] = signals.pwdata
    return payload


def _completion_payload(
    signals: object, is_write: bool
) -> dict[str, object]:
    assert isinstance(signals, Apb3Signals)
    payload: dict[str, object] = {"error": signals.pslverr}
    if not is_write:
        payload["data"] = signals.prdata
    return payload


def _validate_sample(signals: object) -> tuple[str, str] | None:
    assert isinstance(signals, Apb3Signals)
    return None


class Apb3ObservationSession(ApbPhaseObservationSession):
    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        config: Apb3Config | None = None,
        clock: str = "pclk",
        lane: str = "APB",
        reset_lane: str = "reset",
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an APB3 protocol or config")
        protocol = protocol or build_apb3_link(config)
        if protocol.parameters.get("revision") != "APB3":
            raise ValueError("APB3 observation requires an APB3 protocol")
        super().__init__(
            protocol,
            signal_type=Apb3Signals,
            state_type=Apb3ObservationState,
            request_payload=_request_payload,
            completion_payload=_completion_payload,
            validate_sample=_validate_sample,
            stable_signals=("PADDR", "PWRITE", "PWDATA"),
            completion_signals=("PRDATA", "PSLVERR"),
            source="Arm IHI 0024E sections 3.1, 3.3, and 4.1",
            clock=clock,
            lane=lane,
            reset_lane=reset_lane,
        )
