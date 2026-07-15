"""Independent executable state for one LinkProtocol instance."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random
from types import MappingProxyType
from typing import Any, Mapping

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)

from .protocol import LinkProtocol


@dataclass(frozen=True)
class LinkSessionState:
    monitor_states: Mapping[str, Any]
    next_index: int = 0
    causal_edges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "monitor_states", MappingProxyType(dict(self.monitor_states))
        )

    def state_of(self, monitor: str):
        return self.monitor_states[monitor]


@dataclass(frozen=True)
class LinkTrace:
    events: tuple[CanonicalEvent, ...]
    causal_edges: tuple[tuple[int, int], ...]

    def causal_graph(self):
        from protocol_model.semantics import CausalGraph

        return CausalGraph.from_edges(range(len(self.events)), self.causal_edges)


class LinkSession(
    SemanticComponent[CanonicalEvent, LinkSessionState, CanonicalEvent]
):
    """Synchronous product of event schemas and link transaction monitors."""

    def __init__(self, protocol: LinkProtocol):
        self.protocol = protocol
        self.name = f"{protocol.name}.link_session"

    def initial_state(self) -> LinkSessionState:
        return LinkSessionState(
            {
                name: monitor.initial_state()
                for name, monitor in self.protocol.monitors.items()
            }
        )

    def observes(self, event: CanonicalEvent) -> bool:
        try:
            self.protocol.channel_for_event(event.kind)
        except KeyError:
            return False
        return True

    def is_quiescent(self, state: LinkSessionState) -> bool:
        return all(
            monitor.is_quiescent(state.state_of(name))
            for name, monitor in self.protocol.monitors.items()
        )

    def resource_usage(self, state: LinkSessionState) -> Mapping[str, int]:
        """Project executable monitor state onto declared link resources."""

        declared = {item.name for item in self.protocol.semantics.resources}
        usage: dict[str, int] = {name: 0 for name in declared}
        observed = set()
        for name, monitor in self.protocol.monitors.items():
            provider = getattr(monitor, "resource_usage", None)
            if provider is None:
                continue
            for resource, count in provider(state.state_of(name)).items():
                if resource not in declared:
                    raise ValueError(
                        f"monitor {name!r} reports undeclared resource {resource!r}"
                    )
                if resource in observed:
                    raise ValueError(
                        f"multiple monitors report resource {resource!r}"
                    )
                if type(count) is not int or count < 0:
                    raise ValueError(
                        f"resource {resource!r} has invalid usage {count!r}"
                    )
                usage[resource] = count
                observed.add(resource)
        return MappingProxyType(usage)

    def event_offers(self, state: LinkSessionState) -> tuple[EventOffer, ...]:
        """Intersect channel schemas with stateful monitor generation offers."""

        offers = [
            EventOffer.unconstrained(channel.event.name)
            for channel in self.protocol.channels.values()
        ]
        for name, monitor in self.protocol.monitors.items():
            controlled = frozenset(getattr(monitor, "event_kinds", ()))
            if not controlled:
                continue
            provider = getattr(monitor, "event_offers", None)
            if provider is None:
                offers = [offer for offer in offers if offer.kind not in controlled]
                continue
            monitor_offers = tuple(provider(state.state_of(name)))
            constrained: list[EventOffer] = []
            for offer in offers:
                if offer.kind not in controlled:
                    constrained.append(offer)
                    continue
                for monitor_offer in monitor_offers:
                    if monitor_offer.kind != offer.kind:
                        continue
                    merged = offer.merge(monitor_offer)
                    if merged is not None:
                        constrained.append(merged)
            offers = constrained
        return tuple(offers)

    def generate_event(
        self,
        state: LinkSessionState,
        rng: Random,
        *,
        kind: str | None = None,
        offer: EventOffer | None = None,
    ) -> CanonicalEvent:
        """Generate one concrete event currently enabled by all monitors."""

        if kind is not None and offer is not None and kind != offer.kind:
            raise ValueError("kind and offer select different event kinds")
        selected_kind = offer.kind if offer is not None else kind
        candidates: list[EventOffer] = []
        for candidate in self.event_offers(state):
            if selected_kind is not None and candidate.kind != selected_kind:
                continue
            merged = candidate if offer is None else candidate.merge(offer)
            if merged is not None:
                candidates.append(merged)
        if not candidates:
            requested = selected_kind or "any event"
            raise ValueError(f"no enabled generation offer for {requested!r}")
        return self.protocol.generate_event(rng.choice(candidates), rng)

    def step_batch(
        self,
        state: LinkSessionState,
        events,
    ) -> SemanticStep[LinkSessionState, CanonicalEvent]:
        """Apply one ordered same-frame batch with all-or-nothing state commit.

        The caller supplies the lowering order. A fault rolls the complete
        batch back to ``state``; causal edges remain in the candidate state
        only after every event is accepted.
        """

        events = tuple(events)
        kinds = [event.kind for event in events]
        if len(set(kinds)) != len(kinds):
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.batch_channel_multiplicity",
                    "one atomic link frame cannot contain two events of one kind",
                    ConstraintScope.LINK,
                ),
            )
        candidate = state
        emissions = []
        for event in events:
            transition = self.step(candidate, event)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            candidate = transition.state
            emissions.extend(transition.emissions)
        return SemanticStep(candidate, tuple(emissions))

    def step(
        self, state: LinkSessionState, event: CanonicalEvent
    ) -> SemanticStep[LinkSessionState, CanonicalEvent]:
        try:
            channel = self.protocol.channel_for_event(event.kind)
        except KeyError:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.alphabet",
                    f"unknown link event {event.kind!r}",
                    ConstraintScope.LINK,
                ),
            )
        normalized = replace(event, trace_index=state.next_index)
        reasons = channel.event.explain(normalized)
        if reasons:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.{channel.name}.event_schema",
                    "; ".join(reasons),
                    ConstraintScope.EVENT,
                ),
            )

        monitor_states = dict(state.monitor_states)
        predecessors: list[int] = []
        for name, monitor in self.protocol.monitors.items():
            if not monitor.observes(normalized):
                continue
            transition = monitor.step(state.state_of(name), normalized)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            monitor_states[name] = transition.state
            predecessors.extend(transition.causal_predecessors)

        current = state.next_index
        unique_predecessors = tuple(
            item for item in dict.fromkeys(predecessors) if item != current
        )
        edges = state.causal_edges + tuple(
            (predecessor, current) for predecessor in unique_predecessors
        )
        candidate_state = LinkSessionState(
            monitor_states, current + 1, edges
        )
        bounded_resources = tuple(
            resource
            for resource in self.protocol.semantics.resources
            if resource.capacity is not None
        )
        usage = (
            self.resource_usage(candidate_state) if bounded_resources else {}
        )
        for resource in bounded_resources:
            count = usage[resource.name]
            if count > resource.capacity:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.protocol.name}.{resource.name}.capacity",
                        f"resource {resource.name!r} usage {count} exceeds "
                        f"profile capacity {resource.capacity}",
                        resource.scope,
                        resource.name,
                    ),
                )
        return SemanticStep(
            candidate_state,
            (normalized,),
            causal_predecessors=unique_predecessors,
        )
