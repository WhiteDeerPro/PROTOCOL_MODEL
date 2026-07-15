"""Private APB SETUP/ACCESS observation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

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


SignalPayload = Callable[[object], Dict[str, object]]
CompletionPayload = Callable[[object, bool], Dict[str, object]]
SampleValidator = Callable[[object], Optional[Tuple[str, str]]]


@dataclass(frozen=True)
class ApbPhaseObservationState:
    pending_request: CanonicalEvent | None
    link_state: LinkSessionState
    last_tick: int | None = None
    wakeup_hold: bool = False


def validate_boolean_signals(signals: object, names: tuple[str, ...]) -> None:
    for name in names:
        if type(getattr(signals, name)) is not bool:
            raise TypeError(f"APB {name} must be bool")


class ApbPhaseObservationSession(
    SemanticComponent[
        AtomicFrame, ApbPhaseObservationState, CanonicalEvent
    ]
):
    """Validate APB phases and lower a completed transfer to canonical events.

    The engine observes one point-to-point APB link.  Variant packages provide
    the concrete signal type and decide which optional signals contribute to a
    transfer's semantic identity.
    """

    def __init__(
        self,
        protocol: LinkProtocol,
        *,
        signal_type: type,
        state_type: type[ApbPhaseObservationState],
        request_payload: SignalPayload,
        completion_payload: CompletionPayload,
        validate_sample: SampleValidator,
        stable_signals: tuple[str, ...],
        completion_signals: tuple[str, ...],
        source: str,
        wakeup_signal: bool = False,
        clock: str = "pclk",
        lane: str = "APB",
        reset_lane: str = "reset",
    ) -> None:
        expected = {"READ", "WRITE", "READ_RESPONSE", "WRITE_RESPONSE"}
        if set(protocol.channels) != expected:
            raise ValueError("APB observation requires native APB channels")
        self.protocol = protocol
        self.name = f"{protocol.name}.observation"
        self.signal_type = signal_type
        self.state_type = state_type
        self.request_payload = request_payload
        self.completion_payload = completion_payload
        self.validate_sample = validate_sample
        self.stable_signals = stable_signals
        self.completion_signals = completion_signals
        self.source = source
        self.wakeup_signal = wakeup_signal
        self.clock = clock
        self.lane = lane
        self.reset_lane = reset_lane
        self.link_session = protocol.open_session()

    @property
    def semantics(self) -> SemanticFragment:
        constraints = [
            SemanticConstraint(
                f"{self.name}.setup_access",
                "one SETUP cycle is followed by one or more ACCESS cycles",
                ConstraintScope.LINK,
                kind=ConstraintKind.RELATION,
                targets=("PSEL", "PENABLE", "PREADY"),
            ),
            SemanticConstraint(
                f"{self.name}.control_stability",
                "request signals remain stable from SETUP through completed ACCESS",
                ConstraintScope.LINK,
                targets=self.stable_signals,
            ),
            SemanticConstraint(
                f"{self.name}.completion_sampling",
                "completion signals are consumed only at completed ACCESS",
                ConstraintScope.LINK,
                targets=self.completion_signals,
            ),
        ]
        if self.wakeup_signal:
            constraints.append(
                SemanticConstraint(
                    f"{self.name}.wakeup_hold",
                    "sampled PWAKEUP remains asserted until PREADY after overlapping PSEL",
                    ConstraintScope.LINK,
                    targets=("PWAKEUP", "PSEL", "PREADY"),
                )
            )
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=tuple(constraints),
            sources=(self.source,),
        )

    def _state(
        self,
        pending_request: CanonicalEvent | None,
        link_state: LinkSessionState,
        last_tick: int | None,
        wakeup_hold: bool = False,
    ) -> ApbPhaseObservationState:
        return self.state_type(
            pending_request, link_state, last_tick, wakeup_hold
        )

    def initial_state(self) -> ApbPhaseObservationState:
        return self._state(None, self.link_session.initial_state(), None)

    def is_quiescent(self, state: ApbPhaseObservationState) -> bool:
        return (
            state.pending_request is None
            and not state.wakeup_hold
            and self.link_session.is_quiescent(state.link_state)
        )

    def _fault(
        self,
        state: ApbPhaseObservationState,
        rule: str,
        reason: str,
    ) -> SemanticStep[ApbPhaseObservationState, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}",
                reason,
                ConstraintScope.LINK,
                self.lane,
            ),
        )

    def _signals(
        self, state: ApbPhaseObservationState, frame: AtomicFrame
    ) -> object | SemanticStep[ApbPhaseObservationState, CanonicalEvent]:
        if frame.clock != self.clock:
            return self._fault(
                state,
                "clock_domain",
                f"expected clock {self.clock!r}, got {frame.clock!r}",
            )
        if state.last_tick is not None and frame.tick <= state.last_tick:
            return self._fault(
                state,
                "sample_order",
                f"tick {frame.tick} does not follow tick {state.last_tick}",
            )
        try:
            signals = frame.get(self.lane)
        except KeyError:
            return self._fault(
                state, "missing_lane", f"frame has no {self.lane!r}"
            )
        if not isinstance(signals, self.signal_type):
            return self._fault(
                state,
                "observation_type",
                f"APB lane must contain {self.signal_type.__name__}",
            )
        return signals

    def _request(self, signals: object, frame: AtomicFrame) -> CanonicalEvent:
        return CanonicalEvent(
            "WRITE" if getattr(signals, "pwrite") else "READ",
            None,
            self.request_payload(signals),
            source=frame.source,
            clock=frame.clock,
            timestamp=frame.tick,
            sequence=frame.tick,
        )

    def _request_matches(
        self,
        pending: CanonicalEvent,
        signals: object,
        frame: AtomicFrame,
    ) -> bool:
        return (
            pending.semantic_identity
            == self._request(signals, frame).semantic_identity
        )

    def _next_wakeup_hold(
        self,
        state: ApbPhaseObservationState,
        signals: object,
    ) -> bool | SemanticStep[ApbPhaseObservationState, CanonicalEvent]:
        if not self.wakeup_signal:
            return False
        pwakeup = getattr(signals, "pwakeup")
        pready = getattr(signals, "pready")
        if state.wakeup_hold and not pwakeup:
            return self._fault(
                state,
                "wakeup_hold",
                "PWAKEUP deasserted before a sampled PREADY assertion",
            )
        hold = state.wakeup_hold
        if pwakeup and getattr(signals, "psel") and not pready:
            hold = True
        if pready:
            hold = False
        return hold

    def step(
        self, state: ApbPhaseObservationState, frame: AtomicFrame
    ) -> SemanticStep[ApbPhaseObservationState, CanonicalEvent]:
        observed = self._signals(state, frame)
        if isinstance(observed, SemanticStep):
            return observed
        signals = observed
        try:
            reset = frame.get(self.reset_lane)
        except KeyError:
            return self._fault(
                state,
                "missing_reset",
                f"frame has no {self.reset_lane!r}",
            )
        if type(reset) is not bool:
            return self._fault(
                state, "reset_type", "normalized reset must be bool"
            )
        if reset:
            return SemanticStep(
                self._state(
                    None, self.link_session.initial_state(), frame.tick
                )
            )

        invalid = self.validate_sample(signals)
        if invalid is not None:
            return self._fault(state, invalid[0], invalid[1])
        wakeup_hold = self._next_wakeup_hold(state, signals)
        if isinstance(wakeup_hold, SemanticStep):
            return wakeup_hold

        if state.pending_request is None:
            if getattr(signals, "penable"):
                return self._fault(
                    state,
                    "access_without_setup",
                    "PENABLE is asserted without a preceding SETUP cycle",
                )
            if not getattr(signals, "psel"):
                return SemanticStep(
                    self._state(
                        None, state.link_state, frame.tick, wakeup_hold
                    )
                )
            request = self._request(signals, frame)
            transition = self.link_session.step(state.link_state, request)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            normalized = transition.emissions[0]
            return SemanticStep(
                self._state(
                    normalized,
                    transition.state,
                    frame.tick,
                    wakeup_hold,
                ),
                (normalized,),
            )

        if not getattr(signals, "psel") or not getattr(signals, "penable"):
            return self._fault(
                state,
                "missing_access",
                "SETUP must be followed by ACCESS with PSEL and PENABLE asserted",
            )
        if not self._request_matches(state.pending_request, signals, frame):
            return self._fault(
                state,
                "request_stability",
                "APB request fields changed before ACCESS completed",
            )
        if not getattr(signals, "pready"):
            return SemanticStep(
                self._state(
                    state.pending_request,
                    state.link_state,
                    frame.tick,
                    wakeup_hold,
                )
            )

        is_write = state.pending_request.kind == "WRITE"
        response = CanonicalEvent(
            "WRITE_RESPONSE" if is_write else "READ_RESPONSE",
            None,
            self.completion_payload(signals, is_write),
            source=frame.source,
            clock=frame.clock,
            timestamp=frame.tick,
            sequence=frame.tick,
        )
        transition = self.link_session.step(state.link_state, response)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        normalized = transition.emissions[0]
        return SemanticStep(
            self._state(
                None, transition.state, frame.tick, wakeup_hold
            ),
            (normalized,),
        )
