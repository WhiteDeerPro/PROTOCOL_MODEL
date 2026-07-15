"""Ready/valid signal observations lowered to canonical link events."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.link import EventSchema
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from .frame import AtomicFrame


@dataclass(frozen=True)
class ReadyValidSignals:
    valid: bool
    ready: bool
    event: CanonicalEvent | None = None

    def __post_init__(self) -> None:
        if type(self.valid) is not bool or type(self.ready) is not bool:
            raise TypeError("ready/valid signals must be bool values")


@dataclass(frozen=True)
class ReadyValidState:
    held_event: CanonicalEvent | None = None
    stalled_since: int | None = None
    last_tick: int | None = None


@dataclass(frozen=True)
class ReadyValidObserver(
    SemanticComponent[AtomicFrame, ReadyValidState, CanonicalEvent]
):
    """Validate one ready/valid lane and emit accepted transfers."""

    name: str
    lane: str
    transfer: EventSchema
    clock: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.lane:
            raise ValueError("ready/valid observer requires name and lane")

    @property
    def semantics(self) -> SemanticFragment:
        target = (self.lane,)
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.valid_payload",
                    "VALID observations carry a canonical channel event",
                    ConstraintScope.LINK,
                    targets=target,
                ),
                SemanticConstraint(
                    f"{self.name}.valid_stability",
                    "VALID remains asserted from a stalled offer through acceptance",
                    ConstraintScope.LINK,
                    targets=target,
                ),
                SemanticConstraint(
                    f"{self.name}.payload_stability",
                    "the offered canonical event remains stable while stalled",
                    ConstraintScope.LINK,
                    targets=target,
                ),
                SemanticConstraint(
                    f"{self.name}.transfer_acceptance",
                    "a canonical transfer is emitted exactly on a VALID and READY observation",
                    ConstraintScope.LINK,
                    targets=target,
                ),
            ),
        )

    def initial_state(self) -> ReadyValidState:
        return ReadyValidState()

    def is_quiescent(self, state: ReadyValidState) -> bool:
        return state.held_event is None

    def _fault(
        self, state: ReadyValidState, rule: str, reason: str
    ) -> SemanticStep[ReadyValidState, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK, self.lane
            ),
        )

    @staticmethod
    def _same_event(left: CanonicalEvent, right: CanonicalEvent) -> bool:
        return (
            left.kind == right.kind
            and left.key == right.key
            and dict(left.payload) == dict(right.payload)
        )

    def step(
        self, state: ReadyValidState, frame: AtomicFrame
    ) -> SemanticStep[ReadyValidState, CanonicalEvent]:
        if self.clock is not None and frame.clock != self.clock:
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
                state, "missing_lane", f"frame has no observation for {self.lane!r}"
            )
        if not isinstance(signals, ReadyValidSignals):
            return self._fault(
                state,
                "observation_type",
                f"lane {self.lane!r} is not a ReadyValidSignals observation",
            )
        if signals.valid and signals.event is None:
            return self._fault(
                state,
                "valid_payload",
                "VALID is asserted without a canonical channel event",
            )
        if signals.valid:
            reasons = self.transfer.explain(signals.event)  # type: ignore[arg-type]
            if reasons:
                return self._fault(state, "event_schema", "; ".join(reasons))

        held = state.held_event
        if held is not None:
            if not signals.valid:
                return self._fault(
                    state,
                    "valid_stability",
                    f"VALID was withdrawn after stalling at tick {state.stalled_since}",
                )
            assert signals.event is not None
            if not self._same_event(held, signals.event):
                return self._fault(
                    state,
                    "payload_stability",
                    f"offered event changed after stalling at tick {state.stalled_since}",
                )

        next_state = ReadyValidState(last_tick=frame.tick)
        if signals.valid and signals.ready:
            assert signals.event is not None
            accepted = replace(
                signals.event,
                source=frame.source,
                clock=frame.clock,
                timestamp=frame.tick,
                sequence=frame.tick,
            )
            return SemanticStep(next_state, (accepted,))
        if signals.valid:
            assert signals.event is not None
            next_state = ReadyValidState(
                signals.event,
                state.stalled_since if held is not None else frame.tick,
                frame.tick,
            )
        return SemanticStep(next_state)
