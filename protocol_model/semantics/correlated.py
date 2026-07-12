"""Ordered cross-stream burst correlation and completion obligation."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Hashable, Mapping

from protocol_model.domains import EventSpace
from protocol_model.core import CanonicalEvent, SemanticComponent, SemanticFault, SemanticStep


@dataclass(frozen=True)
class DescriptorToken:
    serial: int
    key: Hashable
    expected_beats: int
    event: CanonicalEvent


@dataclass(frozen=True)
class BurstToken:
    serial: int
    events: tuple[CanonicalEvent, ...]


@dataclass(frozen=True)
class CompletionToken:
    descriptor: DescriptorToken
    burst: BurstToken


@dataclass(frozen=True)
class CorrelatedState:
    descriptors: tuple[DescriptorToken, ...] = ()
    current_burst: tuple[CanonicalEvent, ...] = ()
    completed_bursts: tuple[BurstToken, ...] = ()
    completions: tuple[CompletionToken, ...] = ()
    next_descriptor_serial: int = 0
    next_burst_serial: int = 0


@dataclass(frozen=True)
class CorrelatedCardinalityObligation(
    SemanticComponent[CanonicalEvent, CorrelatedState, CanonicalEvent]
):
    """Join ordered descriptors with ID-less bursts, then require completion.

    Descriptor and data streams are independent: a complete burst may arrive
    before its descriptor. Pairing always uses FIFO order. A successful pair
    produces a completion token colored by the descriptor key.
    """

    name: str
    descriptor: EventSpace
    data: EventSpace
    completion: EventSpace
    count_of: Callable[[CanonicalEvent], int]
    final_field: str = "last"
    data_rule: Callable[[CanonicalEvent, int, CanonicalEvent], str | None] | None = None
    data_overrides: Callable[[CanonicalEvent, int, Random], Mapping[str, object]] | None = None

    def __post_init__(self) -> None:
        kinds = {self.descriptor.kind, self.data.kind, self.completion.kind}
        if len(kinds) != 3:
            raise ValueError("descriptor, data, and completion kinds must differ")
        if self.final_field not in self.data.payload:
            raise ValueError(f"data EventSpace has no {self.final_field!r} field")

    def initial_state(self) -> CorrelatedState:
        return CorrelatedState()

    def is_quiescent(self, state: CorrelatedState) -> bool:
        return not (
            state.descriptors
            or state.current_burst
            or state.completed_bursts
            or state.completions
        )

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in {
            self.descriptor.kind,
            self.data.kind,
            self.completion.kind,
        }

    def _causal_predecessors(
        self, state: CorrelatedState, event: CanonicalEvent
    ) -> tuple[int, ...]:
        if event.kind == self.data.kind and state.current_burst:
            previous = state.current_burst[-1].trace_index
            return () if previous is None else (previous,)
        if event.kind == self.completion.kind:
            token = next(
                (
                    item
                    for item in state.completions
                    if item.descriptor.key == event.key
                ),
                None,
            )
            if token is None:
                return ()
            predecessors = (
                token.descriptor.event.trace_index,
                token.burst.events[-1].trace_index,
            )
            return tuple(index for index in predecessors if index is not None)
        return ()

    def _fault(self, state: CorrelatedState, rule: str, reason: str) -> SemanticStep:
        return SemanticStep(state, fault=SemanticFault(f"{self.name}.{rule}", reason))

    def _join(self, state: CorrelatedState):
        descriptors = list(state.descriptors)
        bursts = list(state.completed_bursts)
        completions = list(state.completions)
        while descriptors and bursts:
            descriptor = descriptors[0]
            burst = bursts[0]
            observed = len(burst.events)
            if observed != descriptor.expected_beats:
                return None, SemanticFault(
                    f"{self.name}.beat_count",
                    f"descriptor {descriptor.serial} for key {descriptor.key!r} "
                    f"requires {descriptor.expected_beats} data beats, got {observed}",
                )
            if self.data_rule is not None:
                for beat_index, event in enumerate(burst.events):
                    reason = self.data_rule(descriptor.event, beat_index, event)
                    if reason is not None:
                        return None, SemanticFault(
                            f"{self.name}.data_relation", reason
                        )
            descriptors.pop(0)
            bursts.pop(0)
            completions.append(CompletionToken(descriptor, burst))
        return (
            CorrelatedState(
                tuple(descriptors),
                state.current_burst,
                tuple(bursts),
                tuple(completions),
                state.next_descriptor_serial,
                state.next_burst_serial,
            ),
            None,
        )

    def step(
        self, state: CorrelatedState, event: CanonicalEvent
    ) -> SemanticStep[CorrelatedState, CanonicalEvent]:
        if event.kind == self.descriptor.kind:
            reasons = self.descriptor.explain(event)
            if reasons:
                return self._fault(state, "descriptor_space", "; ".join(reasons))
            count = self.count_of(event)
            if type(count) is not int or count <= 0:
                return self._fault(state, "count", f"invalid burst count {count!r}")
            descriptor = DescriptorToken(
                state.next_descriptor_serial, event.key, count, event
            )
            candidate = CorrelatedState(
                state.descriptors + (descriptor,),
                state.current_burst,
                state.completed_bursts,
                state.completions,
                state.next_descriptor_serial + 1,
                state.next_burst_serial,
            )
            joined, fault = self._join(candidate)
            return SemanticStep(state, fault=fault) if fault else SemanticStep(joined, (event,))

        if event.kind == self.data.kind:
            reasons = self.data.explain(event)
            if reasons:
                return self._fault(state, "data_space", "; ".join(reasons))
            current = state.current_burst + (event,)
            if state.descriptors and self.data_rule is not None:
                reason = self.data_rule(
                    state.descriptors[0].event, len(current) - 1, event
                )
                if reason is not None:
                    return self._fault(state, "data_relation", reason)
            if state.descriptors and len(current) > state.descriptors[0].expected_beats:
                return self._fault(
                    state,
                    "missing_final",
                    f"data burst exceeded {state.descriptors[0].expected_beats} beats without {self.final_field}",
                )
            if (
                state.descriptors
                and len(current) == state.descriptors[0].expected_beats
                and not event.payload[self.final_field]
            ):
                return self._fault(
                    state,
                    "missing_final",
                    f"data beat {len(current)}/{state.descriptors[0].expected_beats} "
                    f"requires {self.final_field}=True",
                )
            if not event.payload[self.final_field]:
                return SemanticStep(
                    CorrelatedState(
                        state.descriptors,
                        current,
                        state.completed_bursts,
                        state.completions,
                        state.next_descriptor_serial,
                        state.next_burst_serial,
                    ),
                    (event,),
                    causal_predecessors=self._causal_predecessors(state, event),
                )
            burst = BurstToken(state.next_burst_serial, current)
            candidate = CorrelatedState(
                state.descriptors,
                (),
                state.completed_bursts + (burst,),
                state.completions,
                state.next_descriptor_serial,
                state.next_burst_serial + 1,
            )
            joined, fault = self._join(candidate)
            return (
                SemanticStep(state, fault=fault)
                if fault
                else SemanticStep(
                    joined,
                    (event,),
                    causal_predecessors=self._causal_predecessors(state, event),
                )
            )

        if event.kind == self.completion.kind:
            reasons = self.completion.explain(event)
            if reasons:
                return self._fault(state, "completion_space", "; ".join(reasons))
            index = next(
                (
                    index
                    for index, token in enumerate(state.completions)
                    if token.descriptor.key == event.key
                ),
                None,
            )
            if index is None:
                return self._fault(
                    state,
                    "orphan_completion",
                    f"completion for key {event.key!r} has no joined descriptor/burst",
                )
            completions = list(state.completions)
            del completions[index]
            return SemanticStep(
                CorrelatedState(
                    state.descriptors,
                    state.current_burst,
                    state.completed_bursts,
                    tuple(completions),
                    state.next_descriptor_serial,
                    state.next_burst_serial,
                ),
                (event,),
                causal_predecessors=self._causal_predecessors(state, event),
            )

        return self._fault(
            state,
            "alphabet",
            f"unexpected event kind {event.kind!r}",
        )

    def sample_data(self, state: CorrelatedState, rng: Random) -> CanonicalEvent:
        """Generate the next legal data beat once its descriptor is known."""

        if not state.descriptors:
            raise ValueError("a descriptor is required for constructive data generation")
        expected = state.descriptors[0].expected_beats
        position = len(state.current_burst) + 1
        if position > expected:
            raise ValueError("current burst already exceeds its descriptor")
        payload = {self.final_field: position == expected}
        if self.data_overrides is not None:
            payload.update(
                self.data_overrides(state.descriptors[0].event, position - 1, rng)
            )
        return self.data.sample_constrained(rng, payload=payload)

    def sample_completion(self, state: CorrelatedState, rng: Random) -> CanonicalEvent:
        if not state.completions:
            raise ValueError("no joined transaction is ready for completion")
        token = rng.choice(state.completions)
        return self.completion.sample_constrained(rng, key=token.descriptor.key)
