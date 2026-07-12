"""Finite execution trace with a causal partial order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from protocol_model.relations import CausalGraph


EventT = TypeVar("EventT")


@dataclass(frozen=True)
class ExecutionTrace(Generic[EventT]):
    events: tuple[EventT, ...]
    causal_graph: CausalGraph
    steps: tuple[tuple[int, ...], ...] = ()

    def __post_init__(self) -> None:
        steps = self.steps or tuple((index,) for index in range(len(self.events)))
        flattened = tuple(index for step in steps for index in step)
        if sorted(flattened) != list(range(len(self.events))):
            raise ValueError("trace steps must partition all event indices exactly once")
        object.__setattr__(self, "steps", steps)

    @classmethod
    def linear(cls, events: tuple[EventT, ...]) -> "ExecutionTrace[EventT]":
        return cls(events, CausalGraph.from_edges(range(len(events)), ()))
