"""Reset-epoch composition for finite-state observation monitors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from protocol_model.core import SemanticComponent, SemanticFault, SemanticStep


ObservationT = TypeVar("ObservationT")
StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class ResetSample(Generic[ObservationT]):
    """One normalized reset level paired with an inner observation."""

    asserted: bool
    observation: ObservationT

    def __post_init__(self) -> None:
        if type(self.asserted) is not bool:
            raise TypeError("asserted must be a bool signal")


@dataclass(frozen=True)
class ResetEpochState(Generic[StateT]):
    epoch: int
    in_reset: bool
    inner_state: StateT


@dataclass(frozen=True)
class ResetEpoch(
    SemanticComponent[ResetSample[ObservationT], ResetEpochState[StateT], OutputT],
    Generic[ObservationT, StateT, OutputT],
):
    """Wrap a monitor with reset clearing and per-epoch state isolation.

    The adapter normalizes active-high/active-low physical reset into
    ``ResetSample.asserted``. While asserted, ``inactive`` constrains the
    observable interface and the inner monitor is held in its initial state.
    """

    name: str
    inner: SemanticComponent[ObservationT, StateT, OutputT]
    inactive: Callable[[ObservationT], bool]
    inactive_reason: str
    initially_asserted: bool = False

    def initial_state(self) -> ResetEpochState[StateT]:
        return ResetEpochState(0, self.initially_asserted, self.inner.initial_state())

    def is_quiescent(self, state: ResetEpochState[StateT]) -> bool:
        return state.in_reset or self.inner.is_quiescent(state.inner_state)

    def step(
        self,
        state: ResetEpochState[StateT],
        sample: ResetSample[ObservationT],
    ) -> SemanticStep[ResetEpochState[StateT], OutputT]:
        if sample.asserted:
            if not self.inactive(sample.observation):
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.reset_inactive", self.inactive_reason
                    ),
                )
            epoch = state.epoch + (0 if state.in_reset else 1)
            return SemanticStep(
                ResetEpochState(epoch, True, self.inner.initial_state())
            )

        transition = self.inner.step(state.inner_state, sample.observation)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        return SemanticStep(
            ResetEpochState(state.epoch, False, transition.state),
            transition.emissions,
        )
