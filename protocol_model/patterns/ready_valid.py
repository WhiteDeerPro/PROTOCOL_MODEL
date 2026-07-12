"""Clocked ready/valid monitor and legal signal-sample generator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from protocol_model.domains import EventSpace
from protocol_model.core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


@dataclass(frozen=True)
class ReadyValidSample:
    """Signals observed at one rising edge.

    ``event`` carries the semantic key and payload represented by the channel
    signals. It is required while VALID is asserted and ignored otherwise.
    """

    cycle: int
    valid: bool
    ready: bool
    event: CanonicalEvent | None = None
    clock: str = "clk"
    source: str = "waveform"

    def __post_init__(self) -> None:
        if self.cycle < 0:
            raise ValueError("cycle must be non-negative")
        if type(self.valid) is not bool or type(self.ready) is not bool:
            raise TypeError("valid and ready must be bool signals")


@dataclass(frozen=True)
class ReadyValidState:
    held_event: CanonicalEvent | None = None
    stalled_since: int | None = None
    last_cycle: int | None = None


@dataclass(frozen=True)
class ClockedReadyValid(
    SemanticComponent[ReadyValidSample, ReadyValidState, CanonicalEvent]
):
    """Mealy monitor for one clocked ready/valid channel.

    A transfer is emitted exactly when VALID and READY are both sampled high.
    Once VALID is observed high without READY, VALID and the semantic event
    must remain stable until a transfer occurs.
    """

    name: str
    transfer: EventSpace
    clock: str = "clk"

    def initial_state(self) -> ReadyValidState:
        return ReadyValidState()

    def is_quiescent(self, state: ReadyValidState) -> bool:
        return state.held_event is None

    @staticmethod
    def _same_semantic_event(left: CanonicalEvent, right: CanonicalEvent) -> bool:
        return (
            left.kind == right.kind
            and left.key == right.key
            and dict(left.payload) == dict(right.payload)
        )

    def _fault(self, state: ReadyValidState, rule: str, reason: str) -> SemanticStep:
        return SemanticStep(state, fault=SemanticFault(f"{self.name}.{rule}", reason))

    def step(
        self, state: ReadyValidState, sample: ReadyValidSample
    ) -> SemanticStep[ReadyValidState, CanonicalEvent]:
        if sample.clock != self.clock:
            return self._fault(
                state,
                "clock_domain",
                f"expected clock {self.clock!r}, got {sample.clock!r}",
            )
        if state.last_cycle is not None and sample.cycle <= state.last_cycle:
            return self._fault(
                state,
                "sample_order",
                f"cycle {sample.cycle} does not follow cycle {state.last_cycle}",
            )
        if sample.valid and sample.event is None:
            return self._fault(
                state,
                "valid_payload",
                "VALID is asserted without a semantic channel event",
            )
        if sample.valid:
            reasons = self.transfer.explain(sample.event)  # type: ignore[arg-type]
            if reasons:
                return self._fault(state, "event_space", "; ".join(reasons))

        held = state.held_event
        if held is not None:
            if not sample.valid:
                return self._fault(
                    state,
                    "valid_stability",
                    f"VALID was withdrawn after stalling at cycle {state.stalled_since}",
                )
            assert sample.event is not None
            if not self._same_semantic_event(held, sample.event):
                return self._fault(
                    state,
                    "payload_stability",
                    f"channel event changed while stalled since cycle {state.stalled_since}",
                )

        next_state = ReadyValidState(last_cycle=sample.cycle)
        outputs = ()
        if sample.valid and sample.ready:
            assert sample.event is not None
            outputs = (
                replace(
                    sample.event,
                    source=sample.source,
                    clock=sample.clock,
                    timestamp=sample.cycle,
                    sequence=sample.cycle,
                ),
            )
        elif sample.valid:
            assert sample.event is not None
            next_state = ReadyValidState(
                held_event=sample.event,
                stalled_since=(
                    state.stalled_since if held is not None else sample.cycle
                ),
                last_cycle=sample.cycle,
            )
        return SemanticStep(next_state, outputs)

    def sample_legal(
        self,
        state: ReadyValidState,
        rng: Random,
        cycle: int,
        *,
        valid_probability: float = 0.7,
        ready_probability: float = 0.7,
        source: str = "generated",
    ) -> ReadyValidSample:
        """Sample one legal observation from this same monitor's state."""

        for name, probability in (
            ("valid_probability", valid_probability),
            ("ready_probability", ready_probability),
        ):
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        ready = rng.random() < ready_probability
        if state.held_event is not None:
            return ReadyValidSample(
                cycle, True, ready, state.held_event, self.clock, source
            )
        valid = rng.random() < valid_probability
        event = self.transfer.sample(rng) if valid else None
        return ReadyValidSample(cycle, valid, ready, event, self.clock, source)
