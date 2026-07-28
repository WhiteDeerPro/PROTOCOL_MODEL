"""One executable transition contract for construction and validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Iterable, Sequence, TypeVar

from .model import ConstraintScope, ResourceDemand


InputT = TypeVar("InputT")
StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class SemanticFault:
    rule: str
    reason: str
    scope: ConstraintScope
    location: str = ""


@dataclass(frozen=True)
class SemanticStep(Generic[StateT, OutputT]):
    state: StateT
    emissions: tuple[OutputT, ...] = ()
    fault: SemanticFault | None = None
    causal_predecessors: tuple[int, ...] = ()
    blocked: ResourceDemand | None = None

    def __post_init__(self) -> None:
        if self.fault is not None and self.blocked is not None:
            raise ValueError("a semantic step cannot be both faulted and blocked")
        if self.blocked is not None and self.emissions:
            raise ValueError("a blocked semantic step cannot emit accepted events")
        if self.blocked is not None and self.causal_predecessors:
            raise ValueError("a blocked semantic step cannot commit causal edges")


@dataclass(frozen=True)
class TraceViolation(Generic[InputT]):
    index: int
    event: InputT
    fault: SemanticFault


@dataclass(frozen=True)
class SemanticRun(Generic[InputT, StateT, OutputT]):
    verdict: Verdict
    final_state: StateT
    emissions: tuple[OutputT, ...]
    violations: tuple[TraceViolation[InputT], ...] = ()
    state_history: tuple[StateT, ...] = ()
    blocked: ResourceDemand | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not Verdict.FAIL


class SemanticComponent(ABC, Generic[InputT, StateT, OutputT]):
    """An executable labeled transition system with optional output actions."""

    name: str

    @abstractmethod
    def initial_state(self) -> StateT:
        raise NotImplementedError

    @abstractmethod
    def step(self, state: StateT, action: InputT) -> SemanticStep[StateT, OutputT]:
        raise NotImplementedError

    def offers(self, state: StateT) -> Sequence[InputT]:
        return ()

    def observes(self, action: InputT) -> bool:
        return True

    def is_quiescent(self, state: StateT) -> bool:
        return True

    def run(self, actions: Iterable[InputT]) -> SemanticRun[InputT, StateT, OutputT]:
        state = self.initial_state()
        history = [state]
        emissions: list[OutputT] = []
        for index, action in enumerate(actions):
            transition = self.step(state, action)
            state = transition.state
            history.append(state)
            emissions.extend(transition.emissions)
            if transition.blocked is not None:
                return SemanticRun(
                    Verdict.INCONCLUSIVE,
                    state,
                    tuple(emissions),
                    state_history=tuple(history),
                    blocked=transition.blocked,
                )
            if transition.fault is not None:
                return SemanticRun(
                    Verdict.FAIL,
                    state,
                    tuple(emissions),
                    (TraceViolation(index, action, transition.fault),),
                    tuple(history),
                )
        verdict = Verdict.PASS if self.is_quiescent(state) else Verdict.INCONCLUSIVE
        return SemanticRun(verdict, state, tuple(emissions), (), tuple(history))
