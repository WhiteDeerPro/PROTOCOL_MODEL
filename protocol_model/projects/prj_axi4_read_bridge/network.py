"""Link instances and global provenance owned by this verification project."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.core import CanonicalEvent, SemanticFault
from protocol_model.engine import ExecutionTrace
from protocol_model.protocols.session import ProtocolSession
from protocol_model.engine.relations import CausalGraph


@dataclass(frozen=True)
class LocatedEvent:
    location: str
    event: CanonicalEvent

    def short(self) -> str:
        return f"{self.location}: {self.event.short()}"


class NetworkRecorder:
    def __init__(self):
        self.events: list[LocatedEvent] = []
        self.edges: list[tuple[int, int]] = []

    def record(
        self,
        location: str,
        event: CanonicalEvent,
        *,
        parents: tuple[int, ...] = (),
    ) -> int:
        index = len(self.events)
        self.events.append(LocatedEvent(location, replace(event, trace_index=index)))
        self.edges.extend((parent, index) for parent in dict.fromkeys(parents))
        return index

    def trace(self) -> ExecutionTrace[LocatedEvent]:
        return ExecutionTrace(
            tuple(self.events),
            CausalGraph.from_edges(range(len(self.events)), self.edges),
        )


class LinkRuntime:
    """One independent ProtocolSession state plus local-to-global provenance."""

    def __init__(self, name: str, session: ProtocolSession, recorder: NetworkRecorder):
        self.name = name
        self.session = session
        self.state = session.initial_state()
        self.recorder = recorder
        self.local_to_global: dict[int, int] = {}

    def accept(
        self, event: CanonicalEvent, *, parents: tuple[int, ...] = ()
    ) -> tuple[CanonicalEvent | None, int | None, SemanticFault | None]:
        local_index = self.state.next_index
        transition = self.session.step(self.state, event)
        if transition.fault is not None:
            return None, None, transition.fault
        accepted = transition.emissions[0]
        local_parents = tuple(
            before
            for before, after in transition.state.causal_edges
            if after == local_index
        )
        global_parents = tuple(
            self.local_to_global[parent]
            for parent in local_parents
            if parent in self.local_to_global
        ) + parents
        global_index = self.recorder.record(
            self.name, accepted, parents=global_parents
        )
        self.local_to_global[local_index] = global_index
        self.state = transition.state
        return accepted, global_index, None

    @property
    def quiescent(self) -> bool:
        return self.session.is_quiescent(self.state)
