"""Reusable clocked setup/access transfer automaton."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from protocol_model.domains import EventSpace
from protocol_model.core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


SampleT = TypeVar("SampleT")


@dataclass(frozen=True)
class TwoPhaseState:
    phase: str = "IDLE"
    request: CanonicalEvent | None = None
    wait_cycles: int = 0
    last_cycle: int | None = None


@dataclass(frozen=True)
class ClockedTwoPhaseTransfer(
    SemanticComponent[SampleT, TwoPhaseState, CanonicalEvent], Generic[SampleT]
):
    """IDLE → SETUP → ACCESS(wait*) → completion Mealy transducer."""

    name: str
    transfer: EventSpace
    cycle_of: Callable[[SampleT], int]
    reset_asserted: Callable[[SampleT], bool]
    selected: Callable[[SampleT], bool]
    enabled: Callable[[SampleT], bool]
    ready: Callable[[SampleT], bool]
    inactive_during_reset: Callable[[SampleT], bool]
    validate_sample: Callable[[SampleT], str | None]
    request_of: Callable[[SampleT], CanonicalEvent]
    completion_of: Callable[[CanonicalEvent, SampleT, int], CanonicalEvent]

    def initial_state(self) -> TwoPhaseState:
        return TwoPhaseState()

    def is_quiescent(self, state: TwoPhaseState) -> bool:
        return state.phase == "IDLE"

    def _fault(self, state: TwoPhaseState, rule: str, reason: str) -> SemanticStep:
        return SemanticStep(state, fault=SemanticFault(f"{self.name}.{rule}", reason))

    @staticmethod
    def _same_request(left: CanonicalEvent, right: CanonicalEvent) -> bool:
        return (
            left.kind == right.kind
            and left.key == right.key
            and dict(left.payload) == dict(right.payload)
        )

    def step(
        self, state: TwoPhaseState, sample: SampleT
    ) -> SemanticStep[TwoPhaseState, CanonicalEvent]:
        cycle = self.cycle_of(sample)
        if cycle < 0:
            return self._fault(state, "cycle", "cycle must be non-negative")
        if state.last_cycle is not None and cycle <= state.last_cycle:
            return self._fault(
                state,
                "sample_order",
                f"cycle {cycle} does not follow cycle {state.last_cycle}",
            )
        reason = self.validate_sample(sample)
        if reason is not None:
            return self._fault(state, "sample", reason)
        if self.reset_asserted(sample):
            if not self.inactive_during_reset(sample):
                return self._fault(
                    state, "reset_inactive", "request signals must be inactive during reset"
                )
            return SemanticStep(TwoPhaseState(last_cycle=cycle))

        psel = self.selected(sample)
        penable = self.enabled(sample)
        if penable and not psel:
            return self._fault(state, "enable_without_select", "enable requires select")

        if state.phase == "IDLE":
            if not psel:
                return SemanticStep(TwoPhaseState(last_cycle=cycle))
            if penable:
                return self._fault(
                    state, "missing_setup", "a transfer must start with enable LOW"
                )
            return SemanticStep(
                TwoPhaseState("SETUP", self.request_of(sample), 0, cycle)
            )

        if not psel or not penable:
            return self._fault(
                state,
                "access_required",
                "SETUP must be followed by selected ACCESS with enable HIGH",
            )
        assert state.request is not None
        current_request = self.request_of(sample)
        if not self._same_request(state.request, current_request):
            return self._fault(
                state,
                "request_stability",
                "request fields changed between SETUP and transfer completion",
            )
        if not self.ready(sample):
            return SemanticStep(
                TwoPhaseState("ACCESS", state.request, state.wait_cycles + 1, cycle)
            )

        completion = self.completion_of(state.request, sample, state.wait_cycles)
        reasons = self.transfer.explain(completion)
        if reasons:
            return self._fault(state, "transfer_space", "; ".join(reasons))
        return SemanticStep(TwoPhaseState(last_cycle=cycle), (completion,))
