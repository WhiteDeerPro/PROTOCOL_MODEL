"""Reset-epoch composition for frame observers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from protocol_model.semantics import (
    ConstraintScope,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from .frame import AtomicFrame


StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class ResetEpochState(Generic[StateT]):
    epoch: int
    in_reset: bool
    inner_state: StateT


@dataclass(frozen=True)
class ResetEpochObserver(
    SemanticComponent[AtomicFrame, ResetEpochState[StateT], OutputT],
    Generic[StateT, OutputT],
):
    """Clear an observer at reset and optionally constrain reset-time signals."""

    name: str
    inner: SemanticComponent[AtomicFrame, StateT, OutputT]
    reset_lane: str
    inactive: Callable[[AtomicFrame], bool]
    inactive_reason: str
    scope: ConstraintScope = ConstraintScope.LINK
    initially_asserted: bool = False

    def initial_state(self) -> ResetEpochState[StateT]:
        return ResetEpochState(
            0, self.initially_asserted, self.inner.initial_state()
        )

    @property
    def semantics(self) -> SemanticFragment:
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.reset_inactive",
                    self.inactive_reason,
                    self.scope,
                    targets=(self.reset_lane,),
                ),
                SemanticConstraint(
                    f"{self.name}.epoch_isolation",
                    "reset starts a fresh inner observation epoch",
                    self.scope,
                    targets=(self.reset_lane,),
                ),
            ),
        )

    def is_quiescent(self, state: ResetEpochState[StateT]) -> bool:
        return state.in_reset or self.inner.is_quiescent(state.inner_state)

    def _fault(
        self, state: ResetEpochState[StateT], rule: str, reason: str
    ) -> SemanticStep[ResetEpochState[StateT], OutputT]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, self.scope, self.reset_lane
            ),
        )

    def step(
        self, state: ResetEpochState[StateT], frame: AtomicFrame
    ) -> SemanticStep[ResetEpochState[StateT], OutputT]:
        try:
            asserted = frame.get(self.reset_lane)
        except KeyError:
            return self._fault(
                state,
                "missing_reset",
                f"frame has no reset observation {self.reset_lane!r}",
            )
        if type(asserted) is not bool:
            return self._fault(
                state, "reset_type", "normalized reset observation must be bool"
            )
        if asserted:
            if not self.inactive(frame):
                return self._fault(state, "reset_inactive", self.inactive_reason)
            epoch = state.epoch + (0 if state.in_reset else 1)
            return SemanticStep(
                ResetEpochState(epoch, True, self.inner.initial_state())
            )

        transition = self.inner.step(state.inner_state, frame)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        return SemanticStep(
            ResetEpochState(state.epoch, False, transition.state),
            transition.emissions,
            causal_predecessors=transition.causal_predecessors,
        )
