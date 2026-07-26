"""Four-phase return-to-zero REQ/ACK signal observation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from protocol_model.semantics import EventSchema
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

from .asynchronous import AsynchronousSample


class FourPhaseState(str, Enum):
    """Observable states of an active-high four-phase exchange."""

    IDLE = "idle_00"
    REQUESTED = "requested_10"
    ACKNOWLEDGED = "acknowledged_11"
    RETURNING = "returning_01"


class FourPhaseDataWindow(str, Enum):
    """How long the offered event identity is required to remain stable."""

    EARLY = "req_assert_to_ack_assert"
    EXTENDED_EARLY = "req_assert_to_req_deassert"
    BROAD = "req_assert_to_ack_deassert"


@dataclass(frozen=True)
class FourPhaseSignals:
    """Normalized active-high REQ/ACK levels and the associated transfer."""

    req: bool
    ack: bool
    event: CanonicalEvent | None = None

    def __post_init__(self) -> None:
        if type(self.req) is not bool or type(self.ack) is not bool:
            raise TypeError("four-phase REQ and ACK observations must be bool")


@dataclass(frozen=True)
class FourPhaseObserverState:
    phase: FourPhaseState = FourPhaseState.IDLE
    held_event: CanonicalEvent | None = None
    request_sequence: int | None = None
    last_sequence: int | None = None
    last_timestamp: int | float | None = None
    epoch: int = 0
    in_reset: bool = False


@dataclass(frozen=True)
class FourPhaseObserver(
    SemanticComponent[
        AsynchronousSample,
        FourPhaseObserverState,
        CanonicalEvent,
    ]
):
    """Validate one edge-complete four-phase lane and emit accepted transfers.

    The normal active-high cycle is ``00 -> 10 -> 11 -> 01 -> 00``.  Every
    state may be held for an arbitrary number of samples, so receiver delay is
    represented without imposing a timeout.  The observer checks logical
    ordering and the selected bundled-data stability window; it does not prove
    synchronizer structure, metastability MTBF, or analog setup/hold timing.
    """

    name: str
    lane: str
    transfer: EventSchema
    data_window: FourPhaseDataWindow = FourPhaseDataWindow.EARLY
    reset_lane: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.lane:
            raise ValueError("four-phase observer requires name and lane")
        if not isinstance(self.data_window, FourPhaseDataWindow):
            object.__setattr__(
                self, "data_window", FourPhaseDataWindow(self.data_window)
            )
        if self.reset_lane == self.lane:
            raise ValueError("reset lane must differ from the handshake lane")

    @property
    def semantics(self) -> SemanticFragment:
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.phase_order",
                    "active-high REQ/ACK follows 00, 10, 11, 01, 00 "
                    "without skipped or simultaneous signal transitions",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                    targets=(self.lane,),
                ),
                SemanticConstraint(
                    f"{self.name}.event_stability",
                    "the offered canonical event remains stable for the "
                    f"{self.data_window.value} data-valid window",
                    ConstraintScope.INTERFACE,
                    targets=(self.lane,),
                ),
                SemanticConstraint(
                    f"{self.name}.acceptance",
                    "one canonical transfer is emitted when ACK asserts after REQ",
                    ConstraintScope.INTERFACE,
                    targets=(self.lane,),
                ),
                SemanticConstraint(
                    f"{self.name}.edge_complete_input",
                    "the input sequence exposes every relevant REQ or ACK transition",
                    ConstraintScope.INTERFACE,
                    targets=(self.lane,),
                ),
            ),
            sources=("four-phase return-to-zero request/acknowledge convention",),
        )

    def initial_state(self) -> FourPhaseObserverState:
        return FourPhaseObserverState()

    def is_quiescent(self, state: FourPhaseObserverState) -> bool:
        return state.phase is FourPhaseState.IDLE and state.held_event is None

    def _fault(
        self,
        state: FourPhaseObserverState,
        rule: str,
        reason: str,
    ) -> SemanticStep[FourPhaseObserverState, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}",
                reason,
                ConstraintScope.INTERFACE,
                self.lane,
            ),
        )

    @staticmethod
    def _same_event(left: CanonicalEvent, right: CanonicalEvent) -> bool:
        return left.semantic_identity == right.semantic_identity

    def _sampled_event(
        self,
        state: FourPhaseObserverState,
        signals: FourPhaseSignals,
    ) -> CanonicalEvent | SemanticStep[FourPhaseObserverState, CanonicalEvent]:
        event = signals.event
        if not isinstance(event, CanonicalEvent):
            return self._fault(
                state,
                "missing_event",
                "the active bundled-data window has no canonical event",
            )
        reasons = self.transfer.explain(event)
        if reasons:
            return self._fault(state, "event_schema", "; ".join(reasons))
        if state.held_event is not None and not self._same_event(
            state.held_event, event
        ):
            return self._fault(
                state,
                "event_stability",
                f"the offered event changed after REQ at sequence "
                f"{state.request_sequence}",
            )
        return event

    def _requires_event(
        self,
        state: FourPhaseObserverState,
        req: bool,
        ack: bool,
    ) -> bool:
        if state.phase is FourPhaseState.IDLE:
            return req and not ack
        if self.data_window is FourPhaseDataWindow.EARLY:
            return state.phase is FourPhaseState.REQUESTED
        if self.data_window is FourPhaseDataWindow.EXTENDED_EARLY:
            return req
        return not (state.phase is FourPhaseState.RETURNING and not ack)

    def _next_state(
        self,
        state: FourPhaseObserverState,
        sample: AsynchronousSample,
        *,
        phase: FourPhaseState,
        held_event: CanonicalEvent | None,
        request_sequence: int | None,
        in_reset: bool = False,
    ) -> FourPhaseObserverState:
        return FourPhaseObserverState(
            phase=phase,
            held_event=held_event,
            request_sequence=request_sequence,
            last_sequence=sample.sequence,
            last_timestamp=(
                sample.timestamp
                if sample.timestamp is not None
                else state.last_timestamp
            ),
            epoch=state.epoch,
            in_reset=in_reset,
        )

    def step(
        self,
        state: FourPhaseObserverState,
        sample: AsynchronousSample,
    ) -> SemanticStep[FourPhaseObserverState, CanonicalEvent]:
        if (
            state.last_sequence is not None
            and sample.sequence <= state.last_sequence
        ):
            return self._fault(
                state,
                "sample_order",
                f"sequence {sample.sequence} does not follow "
                f"{state.last_sequence}",
            )
        if (
            state.last_timestamp is not None
            and sample.timestamp is not None
            and sample.timestamp < state.last_timestamp
        ):
            return self._fault(
                state,
                "timestamp_order",
                f"timestamp {sample.timestamp!r} precedes "
                f"{state.last_timestamp!r}",
            )
        try:
            signals = sample.get(self.lane)
        except KeyError:
            return self._fault(
                state,
                "missing_lane",
                f"sample has no observation for {self.lane!r}",
            )
        if not isinstance(signals, FourPhaseSignals):
            return self._fault(
                state,
                "observation_type",
                f"lane {self.lane!r} is not a FourPhaseSignals observation",
            )

        reset = False
        if self.reset_lane is not None:
            try:
                reset = sample.get(self.reset_lane)
            except KeyError:
                return self._fault(
                    state,
                    "missing_reset",
                    f"sample has no reset observation {self.reset_lane!r}",
                )
            if type(reset) is not bool:
                return self._fault(
                    state,
                    "reset_type",
                    "normalized reset observation must be bool",
                )
        if reset:
            if signals.req or signals.ack:
                return self._fault(
                    state,
                    "reset_idle",
                    "REQ and ACK must both be inactive in the normalized reset epoch",
                )
            epoch = state.epoch + (0 if state.in_reset else 1)
            return SemanticStep(
                FourPhaseObserverState(
                    last_sequence=sample.sequence,
                    last_timestamp=(
                        sample.timestamp
                        if sample.timestamp is not None
                        else state.last_timestamp
                    ),
                    epoch=epoch,
                    in_reset=True,
                )
            )

        if state.last_sequence is None and (signals.req or signals.ack):
            return self._fault(
                state,
                "initial_idle",
                "edge-complete observation must begin from REQ=0 and ACK=0",
            )

        pair = signals.req, signals.ack
        phase = state.phase
        legal_pairs = {
            FourPhaseState.IDLE: {(False, False), (True, False)},
            FourPhaseState.REQUESTED: {(True, False), (True, True)},
            FourPhaseState.ACKNOWLEDGED: {(True, True), (False, True)},
            FourPhaseState.RETURNING: {(False, True), (False, False)},
        }
        if pair not in legal_pairs[phase]:
            return self._fault(
                state,
                "phase_order",
                f"illegal four-phase transition from {phase.value} to "
                f"REQ={int(signals.req)}, ACK={int(signals.ack)}",
            )

        sampled_event = None
        if self._requires_event(state, signals.req, signals.ack):
            sampled_event = self._sampled_event(state, signals)
            if isinstance(sampled_event, SemanticStep):
                return sampled_event

        if phase is FourPhaseState.IDLE:
            if pair == (False, False):
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=phase,
                        held_event=None,
                        request_sequence=None,
                    )
                )
            if pair == (True, False):
                assert sampled_event is not None
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=FourPhaseState.REQUESTED,
                        held_event=sampled_event,
                        request_sequence=sample.sequence,
                    )
                )
        elif phase is FourPhaseState.REQUESTED:
            if pair == (True, False):
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=phase,
                        held_event=state.held_event,
                        request_sequence=state.request_sequence,
                    )
                )
            if pair == (True, True):
                assert state.held_event is not None
                accepted = replace(
                    state.held_event,
                    source=sample.source,
                    clock=None,
                    timestamp=sample.timestamp,
                    sequence=sample.sequence,
                )
                held = (
                    None
                    if self.data_window is FourPhaseDataWindow.EARLY
                    else state.held_event
                )
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=FourPhaseState.ACKNOWLEDGED,
                        held_event=held,
                        request_sequence=state.request_sequence,
                    ),
                    (accepted,),
                )
        elif phase is FourPhaseState.ACKNOWLEDGED:
            if pair == (True, True):
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=phase,
                        held_event=state.held_event,
                        request_sequence=state.request_sequence,
                    )
                )
            if pair == (False, True):
                held = (
                    state.held_event
                    if self.data_window is FourPhaseDataWindow.BROAD
                    else None
                )
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=FourPhaseState.RETURNING,
                        held_event=held,
                        request_sequence=state.request_sequence,
                    )
                )
        else:
            if pair == (False, True):
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=phase,
                        held_event=state.held_event,
                        request_sequence=state.request_sequence,
                    )
                )
            if pair == (False, False):
                return SemanticStep(
                    self._next_state(
                        state,
                        sample,
                        phase=FourPhaseState.IDLE,
                        held_event=None,
                        request_sequence=None,
                    )
                )

        raise AssertionError("validated four-phase pair was not handled")


__all__ = [
    "FourPhaseDataWindow",
    "FourPhaseObserver",
    "FourPhaseObserverState",
    "FourPhaseSignals",
    "FourPhaseState",
]
