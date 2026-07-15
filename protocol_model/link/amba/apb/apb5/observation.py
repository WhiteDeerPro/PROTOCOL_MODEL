"""APB5 SETUP/ACCESS, wake-up, user, and RME observation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from .._common.observation import (
    ApbPhaseObservationSession,
    ApbPhaseObservationState,
    validate_boolean_signals,
)
from .definition import Apb5Config, build_apb5_link


@dataclass(frozen=True)
class Apb5Signals:
    psel: bool
    penable: bool
    pready: bool = True
    paddr: int = 0
    pwrite: bool = False
    pwdata: int = 0
    pstrb: int = 0
    pprot: int = 0
    pnse: bool = False
    pwakeup: bool = False
    pauser: int = 0
    pwuser: int = 0
    prdata: int = 0
    pslverr: bool = False
    pruser: int = 0
    pbuser: int = 0

    def __post_init__(self) -> None:
        validate_boolean_signals(
            self,
            (
                "psel",
                "penable",
                "pready",
                "pwrite",
                "pnse",
                "pwakeup",
                "pslverr",
            ),
        )


@dataclass(frozen=True)
class Apb5ObservationState(ApbPhaseObservationState):
    pass


class Apb5ObservationSession(ApbPhaseObservationSession):
    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        config: Apb5Config | None = None,
        clock: str = "pclk",
        lane: str = "APB",
        reset_lane: str = "reset",
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an APB5 protocol or config")
        protocol = protocol or build_apb5_link(config)
        if protocol.parameters.get("revision") != "APB5":
            raise ValueError("APB5 observation requires an APB5 protocol")
        if protocol.parameters.get("check_type") != "none":
            raise ValueError(
                "APB5 observation currently requires check_type=none"
            )
        self.pprot_present = bool(protocol.parameters["pprot_present"])
        self.pstrb_present = bool(protocol.parameters["pstrb_present"])
        self.wakeup_signal = bool(protocol.parameters["wakeup_signal"])
        self.user_request_width = int(
            protocol.parameters["user_request_width"]
        )
        self.user_data_width = int(protocol.parameters["user_data_width"])
        self.user_response_width = int(
            protocol.parameters["user_response_width"]
        )
        self.rme_support = bool(protocol.parameters["rme_support"])

        def request_payload(signals: object) -> dict[str, object]:
            assert isinstance(signals, Apb5Signals)
            payload: dict[str, object] = {"addr": signals.paddr}
            if self.pprot_present:
                payload["prot"] = signals.pprot
            if self.rme_support:
                payload["nse"] = signals.pnse
            if self.user_request_width:
                payload["auser"] = signals.pauser
            if signals.pwrite:
                payload["data"] = signals.pwdata
                if self.pstrb_present:
                    payload["strb"] = signals.pstrb
                if self.user_data_width:
                    payload["wuser"] = signals.pwuser
            return payload

        def completion_payload(
            signals: object, is_write: bool
        ) -> dict[str, object]:
            assert isinstance(signals, Apb5Signals)
            payload: dict[str, object] = {"error": signals.pslverr}
            if not is_write:
                payload["data"] = signals.prdata
                if self.user_data_width:
                    payload["ruser"] = signals.pruser
            if self.user_response_width:
                payload["buser"] = signals.pbuser
            return payload

        def validate_sample(signals: object) -> tuple[str, str] | None:
            assert isinstance(signals, Apb5Signals)
            absent_values = (
                (not self.pprot_present, signals.pprot, "PPROT"),
                (not self.pstrb_present, signals.pstrb, "PSTRB"),
                (not self.rme_support, signals.pnse, "PNSE"),
                (not self.wakeup_signal, signals.pwakeup, "PWAKEUP"),
                (
                    not self.user_request_width,
                    signals.pauser,
                    "PAUSER",
                ),
                (not self.user_data_width, signals.pwuser, "PWUSER"),
                (not self.user_data_width, signals.pruser, "PRUSER"),
                (
                    not self.user_response_width,
                    signals.pbuser,
                    "PBUSER",
                ),
            )
            for absent, value, name in absent_values:
                if absent and value:
                    return (
                        f"absent_{name.lower()}",
                        f"normalized {name} must be zero when the signal is absent",
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
        if self.rme_support:
            stable_signals.append("PNSE")
        if self.user_request_width:
            stable_signals.append("PAUSER")
        if self.pstrb_present:
            stable_signals.append("PSTRB")
        if self.user_data_width:
            stable_signals.append("PWUSER")
        completion_signals = ["PRDATA", "PSLVERR"]
        if self.user_data_width:
            completion_signals.append("PRUSER")
        if self.user_response_width:
            completion_signals.append("PBUSER")
        super().__init__(
            protocol,
            signal_type=Apb5Signals,
            state_type=Apb5ObservationState,
            request_payload=request_payload,
            completion_payload=completion_payload,
            validate_sample=validate_sample,
            stable_signals=tuple(stable_signals),
            completion_signals=tuple(completion_signals),
            source="Arm IHI 0024E sections 3.1-3.8 and 4.1; parity disabled by profile",
            wakeup_signal=self.wakeup_signal,
            clock=clock,
            lane=lane,
            reset_lane=reset_lane,
        )
