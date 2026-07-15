"""Reusable restrictions for inactive events and observed values.

The two components in this module deliberately act at different boundaries:
``ForbiddenEventMonitor`` constrains canonical link events, while
``QuietConstraint`` constrains values in an observation stream.  Display
filtering belongs to :mod:`protocol_model.visualization` and is not evidence
for either restriction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


ObservationT = TypeVar("ObservationT")
ValueT = TypeVar("ValueT")
_UNSET = object()


class QuietMode(str, Enum):
    """How an observation profile treats a projected value."""

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
    """Ignore, stabilize, or tie one value projected from observations.

    ``IGNORE`` is an observation-coverage choice: it performs no check and
    does not establish that the underlying interface is inactive.
    """

    name: str
    mode: QuietMode
    value_of: Callable[[ObservationT], ValueT] = lambda observation: observation
    expected: object = _UNSET
    scope: ConstraintScope = ConstraintScope.LINK
    location: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("quiet constraint requires a name")
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
                        f"observed value must be {self.expected!r}, got {value!r}",
                        self.scope,
                        self.location,
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
                    f"observed value changed from {state.baseline!r} to {value!r}",
                    self.scope,
                    self.location,
                ),
            )
        return SemanticStep(state)


@dataclass(frozen=True)
class ForbiddenEventMonitor(
    SemanticComponent[CanonicalEvent, None, CanonicalEvent]
):
    """Reject selected canonical event kinds in a refined LinkProtocol."""

    name: str
    event_kinds: frozenset[str]
    reason: str = "disabled by the link profile"

    def __post_init__(self) -> None:
        if not self.name or not self.event_kinds or any(
            not kind for kind in self.event_kinds
        ):
            raise ValueError("forbidden-event monitor requires a name and event kinds")

    def initial_state(self) -> None:
        return None

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def event_offers(self, state: None) -> tuple[EventOffer, ...]:
        return ()

    def step(
        self, state: None, event: CanonicalEvent
    ) -> SemanticStep[None, CanonicalEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.forbidden_event",
                f"{event.kind} is {self.reason}",
                ConstraintScope.LINK,
                event.kind,
            ),
        )
