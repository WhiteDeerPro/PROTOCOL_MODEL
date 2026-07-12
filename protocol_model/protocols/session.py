"""Per-link runtime composition of channel schemas and transaction monitors."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from itertools import permutations
from types import MappingProxyType
from typing import Any, Mapping

from protocol_model.core import (
    CanonicalEvent,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.engine import ExecutionTrace
from protocol_model.relations import CausalGraph

from .spec import ProtocolSpec


@dataclass(frozen=True)
class ProtocolSessionState:
    monitor_states: Mapping[str, Any]
    next_index: int = 0
    causal_edges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "monitor_states", MappingProxyType(dict(self.monitor_states))
        )

    def state_of(self, name: str):
        return self.monitor_states[name]


class ProtocolSession(
    SemanticComponent[CanonicalEvent, ProtocolSessionState, CanonicalEvent]
):
    """A runtime synchronous product over one elaborated protocol link."""

    def __init__(self, spec: ProtocolSpec):
        self.spec = spec
        self.name = f"{spec.name}.session"
        channels_by_kind = {
            channel.transfer.kind: channel for channel in spec.channels.values()
        }
        if len(channels_by_kind) != len(spec.channels):
            raise ValueError("channel transfer kinds must be unique within a session")
        self.channels_by_kind = MappingProxyType(channels_by_kind)

    def initial_state(self) -> ProtocolSessionState:
        return ProtocolSessionState(
            {
                name: monitor.initial_state()
                for name, monitor in self.spec.transaction_models.items()
            }
        )

    def is_quiescent(self, state: ProtocolSessionState) -> bool:
        return all(
            monitor.is_quiescent(state.state_of(name))
            for name, monitor in self.spec.transaction_models.items()
        )

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.channels_by_kind

    @staticmethod
    def _semantic_value(value):
        if isinstance(value, CanonicalEvent):
            return (
                "event",
                value.kind,
                value.key,
                tuple(sorted(value.payload.items())),
            )
        if isinstance(value, Mapping):
            return tuple(
                sorted(
                    (
                        repr(key),
                        ProtocolSession._semantic_value(item),
                    )
                    for key, item in value.items()
                )
            )
        if isinstance(value, (tuple, list)):
            return tuple(ProtocolSession._semantic_value(item) for item in value)
        if is_dataclass(value):
            return (
                type(value).__name__,
                tuple(
                    (
                        field.name,
                        ProtocolSession._semantic_value(getattr(value, field.name)),
                    )
                    for field in fields(value)
                ),
            )
        return value

    def can_cooccur(
        self, state: ProtocolSessionState, events: tuple[CanonicalEvent, ...]
    ) -> bool:
        """Check the finite diamond property for a same-cycle event set."""

        if not events or len({event.kind for event in events}) != len(events):
            return False
        signatures = []
        for ordering in permutations(events):
            current = state
            for event in ordering:
                transition = self.step(current, event)
                if transition.fault is not None:
                    return False
                current = transition.state
            signatures.append(self._semantic_value(current.monitor_states))
        return all(signature == signatures[0] for signature in signatures[1:])

    def step(
        self, state: ProtocolSessionState, event: CanonicalEvent
    ) -> SemanticStep[ProtocolSessionState, CanonicalEvent]:
        channel = self.channels_by_kind.get(event.kind)
        if channel is None:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.alphabet", f"unknown channel event {event.kind!r}"
                ),
            )
        normalized = replace(event, trace_index=state.next_index)
        reasons = channel.transfer.explain(normalized)
        if reasons:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.{channel.name}.event_space", "; ".join(reasons)
                ),
            )

        monitor_states = dict(state.monitor_states)
        predecessors = []
        for name, monitor in self.spec.transaction_models.items():
            if not monitor.observes(normalized):
                continue
            local_state = state.state_of(name)
            transition = monitor.step(local_state, normalized)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            predecessors.extend(transition.causal_predecessors)
            monitor_states[name] = transition.state

        current = state.next_index
        edges = state.causal_edges + tuple(
            (predecessor, current)
            for predecessor in dict.fromkeys(predecessors)
            if predecessor != current
        )
        return SemanticStep(
            ProtocolSessionState(monitor_states, current + 1, edges),
            (normalized,),
        )

    def execution_trace(
        self,
        state: ProtocolSessionState,
        events: tuple[CanonicalEvent, ...],
        steps: tuple[tuple[int, ...], ...] = (),
    ) -> ExecutionTrace[CanonicalEvent]:
        graph = CausalGraph.from_edges(range(len(events)), state.causal_edges)
        return ExecutionTrace(events, graph, steps)
