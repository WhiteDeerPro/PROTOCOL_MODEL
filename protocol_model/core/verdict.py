"""Protocol-independent verdicts and violation diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Sequence, TypeVar


EventT = TypeVar("EventT")
StateT = TypeVar("StateT")


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class TraceViolation(Generic[EventT]):
    index: int
    event: EventT | None
    reason: str
    enabled: tuple[EventT, ...] = ()
    rule: str | None = None


@dataclass(frozen=True)
class TraceValidation(Generic[EventT, StateT]):
    verdict: Verdict
    final_state: StateT
    violations: tuple[TraceViolation[EventT], ...] = ()
    state_history: tuple[StateT, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict == Verdict.PASS
