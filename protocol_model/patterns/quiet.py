"""Observation policies for unused, unobserved, or tied-off ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar

from protocol_model.core import SemanticComponent, SemanticFault, SemanticStep


ObservationT = TypeVar("ObservationT")
ValueT = TypeVar("ValueT")
_UNSET = object()


class QuietMode(str, Enum):
    """How a verification profile treats a port observation."""

    IGNORE = "ignore"
    STABLE = "stable"
    TIED = "tied"


@dataclass(frozen=True)
class QuietState(Generic[ValueT]):
    seen: bool = False
    baseline: ValueT | None = None


@dataclass(frozen=True)
class QuietConstraint(
    SemanticComponent[ObservationT, QuietState[ValueT], object],
    Generic[ObservationT, ValueT],
):
    """Project away a port, require stability, or require a tied value.

    ``IGNORE`` deliberately produces no semantic event and performs no check.
    It is an observation-coverage decision, not evidence that the port obeyed a
    protocol. ``STABLE`` learns the first projected value and rejects changes.
    ``TIED`` rejects every projected value different from ``expected``.
    """

    name: str
    mode: QuietMode
    value_of: Callable[[ObservationT], ValueT] = lambda observation: observation
    expected: object = _UNSET

    def __post_init__(self) -> None:
        if self.mode is QuietMode.TIED and self.expected is _UNSET:
            raise ValueError("TIED quiet constraint requires an expected value")
        if self.mode is not QuietMode.TIED and self.expected is not _UNSET:
            raise ValueError("expected is only meaningful in TIED mode")

    def initial_state(self) -> QuietState[ValueT]:
        return QuietState()

    def step(
        self, state: QuietState[ValueT], observation: ObservationT
    ) -> SemanticStep[QuietState[ValueT], object]:
        if self.mode is QuietMode.IGNORE:
            return SemanticStep(state)

        value = self.value_of(observation)
        if self.mode is QuietMode.TIED:
            if value != self.expected:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.tied_value",
                        f"quiet port requires {self.expected!r}, got {value!r}",
                    ),
                )
            return SemanticStep(QuietState(True, value))

        if not state.seen:
            return SemanticStep(QuietState(True, value))
        if value != state.baseline:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.changed",
                    f"quiet port changed from {state.baseline!r} to {value!r}",
                ),
            )
