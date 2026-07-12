"""Single executable semantic-component contract for generation and checking."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Iterable, Sequence, TypeVar

from .verdict import TraceViolation, Verdict


InputT = TypeVar("InputT")
StateT = TypeVar("StateT")
OutputT = TypeVar("OutputT")


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    INTERNAL = "internal"


@dataclass(frozen=True)
class PortSpec:
    name: str
    direction: PortDirection
    description: str = ""


@dataclass(frozen=True)
class SemanticFault:
    rule: str
    reason: str
    scope: str = "SPEC"


@dataclass(frozen=True)
class SemanticStep(Generic[StateT, OutputT]):
    state: StateT
    emissions: tuple[OutputT, ...] = ()
    fault: SemanticFault | None = None
    causal_predecessors: tuple[int, ...] = ()


@dataclass(frozen=True)
class SemanticRun(Generic[InputT, StateT, OutputT]):
    verdict: Verdict
    final_state: StateT
    emissions: tuple[OutputT, ...]
    violations: tuple[TraceViolation[InputT], ...] = ()
    state_history: tuple[StateT, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict != Verdict.FAIL


class SemanticComponent(ABC, Generic[InputT, StateT, OutputT]):
    """An executable labeled transition system with optional output actions.

    Validation supplies externally observed labels to ``step``. Constructive
    generators may obtain candidates from ``offers`` but must submit the chosen
    candidate to the same ``step`` method. There is no separate validation rule.
    """

    name: str
    ports: tuple[PortSpec, ...] = ()

    @abstractmethod
    def initial_state(self) -> StateT:
        raise NotImplementedError

    @abstractmethod
    def step(self, state: StateT, action: InputT) -> SemanticStep[StateT, OutputT]:
        raise NotImplementedError

    def offers(self, state: StateT) -> Sequence[InputT]:
        return ()

    def is_quiescent(self, state: StateT) -> bool:
        return True

    def observes(self, action: InputT) -> bool:
        return True

    def run(self, actions: Iterable[InputT]) -> SemanticRun[InputT, StateT, OutputT]:
        state = self.initial_state()
        states = [state]
        emissions = []
        for index, action in enumerate(actions):
            transition = self.step(state, action)
            if transition.fault is not None:
                violation = TraceViolation(
                    index=index,
                    event=action,
                    reason=transition.fault.reason,
                    rule=transition.fault.rule,
                )
                return SemanticRun(
                    Verdict.FAIL,
                    state,
                    tuple(emissions),
                    (violation,),
                    tuple(states),
                )
            state = transition.state
            states.append(state)
            emissions.extend(transition.emissions)
        verdict = Verdict.PASS if self.is_quiescent(state) else Verdict.INCONCLUSIVE
        return SemanticRun(verdict, state, tuple(emissions), (), tuple(states))
