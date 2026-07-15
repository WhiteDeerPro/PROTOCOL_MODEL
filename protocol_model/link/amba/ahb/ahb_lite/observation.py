"""AHB-Lite address/data pipeline observation and wait-state validation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol, LinkSessionState
from protocol_model.observation import AtomicFrame
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintKind,
    ConstraintScope,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from .definition import AHB_BURSTS, AhbLiteConfig, build_ahb_lite_link


@dataclass(frozen=True)
class AhbSignals:
    hsel: bool
    hready: bool
    htrans: str = "IDLE"
    haddr: int = 0
    hwrite: bool = False
    hsize: int = 0
    hburst: str = "SINGLE"
    hprot: int = 0
    hmastlock: bool = False
    hwdata: int = 0
    hrdata: int = 0
    hresp: str = "OKAY"

    def __post_init__(self) -> None:
        for name in ("hsel", "hready", "hwrite", "hmastlock"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"AHB {name} must be bool")
        if self.htrans not in {"IDLE", "BUSY", "NONSEQ", "SEQ"}:
            raise ValueError(f"unknown HTRANS {self.htrans!r}")
        if self.hburst not in AHB_BURSTS:
            raise ValueError(f"unknown HBURST {self.hburst!r}")
        if self.hresp not in {"OKAY", "ERROR"}:
            raise ValueError(f"unknown HRESP {self.hresp!r}")


@dataclass(frozen=True)
class AhbAddressPhase:
    addr: int
    write: bool
    size: int
    burst: str
    trans: str
    prot: int
    lock: bool
    source: str
    clock: str
    tick: int


@dataclass(frozen=True)
class AhbObservationState:
    pending_address: AhbAddressPhase | None
    held_address: AhbAddressPhase | None
    held_write_data: int | None
    error_first_cycle: bool
    link_state: LinkSessionState
    last_tick: int | None = None


class AhbObservationSession(
    SemanticComponent[AtomicFrame, AhbObservationState, CanonicalEvent]
):
    """Lower completed AHB data phases while retaining pipeline state."""

    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        config: AhbLiteConfig | None = None,
        clock: str = "hclk",
        lane: str = "AHB",
        reset_lane: str = "reset",
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an AHB-Lite protocol or config")
        self.protocol = protocol or build_ahb_lite_link(config)
        expected = {
            "READ",
            "WRITE",
            "WRITE_DATA",
            "READ_RESPONSE",
            "WRITE_RESPONSE",
        }
        if set(self.protocol.channels) != expected:
            raise ValueError("AHB observation requires native AHB-Lite channels")
        self.name = f"{self.protocol.name}.observation"
        self.clock = clock
        self.lane = lane
        self.reset_lane = reset_lane
        self.link_session = self.protocol.open_session()

    @property
    def semantics(self) -> SemanticFragment:
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.pipeline",
                    "the current address phase overlaps the previous transfer data phase",
                    ConstraintScope.LINK,
                    kind=ConstraintKind.RELATION,
                    targets=("HADDR", "HTRANS", "HREADY"),
                ),
                SemanticConstraint(
                    f"{self.name}.wait_stability",
                    "an active address offer and current write data remain stable while HREADY is low",
                    ConstraintScope.LINK,
                    targets=("HADDR", "HTRANS", "HWDATA"),
                ),
                SemanticConstraint(
                    f"{self.name}.two_cycle_error",
                    "ERROR starts with HREADY low and completes with HREADY high in the following cycle",
                    ConstraintScope.LINK,
                    kind=ConstraintKind.RELATION,
                    targets=("HRESP", "HREADY"),
                ),
            ),
            sources=("Arm IHI 0033C sections 3.1, 3.7, and 5.1",),
        )

    def initial_state(self) -> AhbObservationState:
        return AhbObservationState(
            None, None, None, False, self.link_session.initial_state()
        )

    def is_quiescent(self, state: AhbObservationState) -> bool:
        return (
            state.pending_address is None
            and state.held_address is None
            and not state.error_first_cycle
            and self.link_session.is_quiescent(state.link_state)
        )

    def _fault(
        self, state: AhbObservationState, rule: str, reason: str
    ) -> SemanticStep[AhbObservationState, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK, self.lane
            ),
        )

    def _address_phase(
        self, signals: AhbSignals, frame: AtomicFrame
    ) -> AhbAddressPhase | None:
        if not signals.hsel or signals.htrans not in {"NONSEQ", "SEQ"}:
            return None
        return AhbAddressPhase(
            signals.haddr,
            signals.hwrite,
            signals.hsize,
            signals.hburst,
            signals.htrans,
            signals.hprot,
            signals.hmastlock,
            frame.source,
            frame.clock,
            frame.tick,
        )

    def _request(self, address: AhbAddressPhase) -> CanonicalEvent:
        payload: dict[str, object] = {
            "addr": address.addr,
            "size": address.size,
            "burst": address.burst,
            "trans": address.trans,
            "prot": address.prot,
            "lock": address.lock,
        }
        return CanonicalEvent(
            "WRITE" if address.write else "READ",
            None,
            payload,
            source=address.source,
            clock=address.clock,
            timestamp=address.tick,
            sequence=address.tick,
        )

    def _write_data(
        self, signals: AhbSignals, frame: AtomicFrame
    ) -> CanonicalEvent:
        return CanonicalEvent(
            "WRITE_DATA",
            None,
            {"data": signals.hwdata},
            source=frame.source,
            clock=frame.clock,
            timestamp=frame.tick,
            sequence=frame.tick,
        )

    @staticmethod
    def _response(
        address: AhbAddressPhase, signals: AhbSignals, frame: AtomicFrame
    ) -> CanonicalEvent:
        payload: dict[str, object] = {"resp": signals.hresp}
        if not address.write:
            payload["data"] = signals.hrdata
        return CanonicalEvent(
            "WRITE_RESPONSE" if address.write else "READ_RESPONSE",
            None,
            payload,
            source=frame.source,
            clock=frame.clock,
            timestamp=frame.tick,
            sequence=frame.tick,
        )

    def step(
        self, state: AhbObservationState, frame: AtomicFrame
    ) -> SemanticStep[AhbObservationState, CanonicalEvent]:
        if frame.clock != self.clock:
            return self._fault(
                state, "clock_domain", f"expected {self.clock!r}, got {frame.clock!r}"
            )
        if state.last_tick is not None and frame.tick <= state.last_tick:
            return self._fault(
                state,
                "sample_order",
                f"tick {frame.tick} does not follow tick {state.last_tick}",
            )
        try:
            signals = frame.get(self.lane)
            reset = frame.get(self.reset_lane)
        except KeyError as missing:
            return self._fault(state, "missing_observation", f"missing {missing.args[0]!r}")
        if not isinstance(signals, AhbSignals):
            return self._fault(
                state, "observation_type", "AHB lane must contain AhbSignals"
            )
        if type(reset) is not bool:
            return self._fault(state, "reset_type", "normalized reset must be bool")
        if reset:
            if signals.htrans != "IDLE":
                return self._fault(
                    state, "reset_idle", "HTRANS must indicate IDLE during reset"
                )
            if not signals.hready:
                return self._fault(
                    state, "reset_ready", "normalized HREADY must be high during reset"
                )
            return SemanticStep(
                AhbObservationState(
                    None,
                    None,
                    None,
                    False,
                    self.link_session.initial_state(),
                    frame.tick,
                )
            )

        current_address = self._address_phase(signals, frame)
        if state.error_first_cycle:
            if not signals.hready or signals.hresp != "ERROR":
                return self._fault(
                    state,
                    "error_second_cycle",
                    "the second ERROR cycle requires HRESP=ERROR and HREADY high",
                )
        elif not signals.hready and signals.hresp == "ERROR":
            if state.pending_address is None:
                return self._fault(
                    state, "orphan_error", "ERROR response has no current data phase"
                )

        if state.pending_address is None and not signals.hready:
            return self._fault(
                state,
                "idle_wait",
                "HREADY cannot extend an IDLE/BUSY data phase in this normalized link",
            )

        if state.pending_address is not None and not signals.hready:
            held_address = state.held_address
            if not state.error_first_cycle:
                if held_address is not None and current_address != held_address:
                    return self._fault(
                        state,
                        "address_stability",
                        "active address/control changed while HREADY was low",
                    )
                if held_address is None and current_address is not None:
                    held_address = current_address
            held_data = state.held_write_data
            if state.pending_address.write:
                observed_data = signals.hwdata
                if held_data is not None and observed_data != held_data:
                    return self._fault(
                        state,
                        "write_data_stability",
                        "HWDATA changed while HREADY was low",
                    )
                held_data = observed_data
            return SemanticStep(
                AhbObservationState(
                    state.pending_address,
                    held_address,
                    held_data,
                    signals.hresp == "ERROR",
                    state.link_state,
                    frame.tick,
                )
            )

        if state.held_address is not None and not state.error_first_cycle:
            if current_address != state.held_address:
                return self._fault(
                    state,
                    "address_stability",
                    "active address/control changed before HREADY completed the wait",
                )
        if state.held_write_data is not None and state.pending_address is not None:
            if state.pending_address.write and (
                signals.hwdata != state.held_write_data
            ):
                return self._fault(
                    state,
                    "write_data_stability",
                    "HWDATA changed before the transfer completed",
                )
        if signals.hresp == "ERROR" and not state.error_first_cycle:
            return self._fault(
                state,
                "error_first_cycle",
                "AHB ERROR must begin with HREADY low before its completing cycle",
            )

        actions = []
        if state.pending_address is not None:
            response = self._response(state.pending_address, signals, frame)
            if state.pending_address.write:
                actions.append(self._write_data(signals, frame))
            actions.append(response)
        if current_address is not None:
            actions.append(self._request(current_address))

        link_state = state.link_state
        emissions: tuple[CanonicalEvent, ...] = ()
        if actions:
            transition = self.link_session.step_batch(state.link_state, actions)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            link_state = transition.state
            emissions = transition.emissions

        return SemanticStep(
            AhbObservationState(
                current_address,
                None,
                None,
                False,
                link_state,
                frame.tick,
            ),
            emissions,
        )
