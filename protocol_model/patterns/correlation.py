"""Reusable burst assembly, FIFO correlation, and completion resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Hashable

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


@dataclass(frozen=True)
class BurstToken:
    serial: int
    events: tuple[CanonicalEvent, ...]


@dataclass(frozen=True)
class BurstAssemblerState:
    current: tuple[CanonicalEvent, ...] = ()
    next_serial: int = 0


@dataclass(frozen=True)
class BurstAssembler(
    SemanticComponent[CanonicalEvent, BurstAssemblerState, BurstToken]
):
    """Assemble explicit final-marked bursts or implicit single-beat tokens."""

    name: str
    beat_kind: str
    final_field: str | None = "last"

    def initial_state(self) -> BurstAssemblerState:
        return BurstAssemblerState()

    def is_quiescent(self, state: BurstAssemblerState) -> bool:
        return not state.current

    def step(
        self, state: BurstAssemblerState, event: CanonicalEvent
    ) -> SemanticStep[BurstAssemblerState, BurstToken]:
        if event.kind != self.beat_kind:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.alphabet",
                    f"expected {self.beat_kind!r}, got {event.kind!r}",
                    ConstraintScope.LINK,
                ),
            )
        if event.trace_index is None:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.trace_index",
                    "burst beats must be normalized by a LinkSession",
                    ConstraintScope.LINK,
                ),
            )
        final = True if self.final_field is None else event.payload.get(self.final_field)
        if type(final) is not bool:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.final_field",
                    f"{self.final_field!r} must be a bool payload field",
                    ConstraintScope.LINK,
                ),
            )
        predecessor = (
            state.current[-1].trace_index if state.current else None
        )
        events = state.current + (event,)
        causal = () if predecessor is None else (predecessor,)
        if final:
            token = BurstToken(state.next_serial, events)
            return SemanticStep(
                BurstAssemblerState((), state.next_serial + 1),
                (token,),
                causal_predecessors=causal,
            )
        return SemanticStep(
            BurstAssemblerState(events, state.next_serial),
            causal_predecessors=causal,
        )


@dataclass(frozen=True)
class DescriptorToken:
    serial: int
    key: Hashable
    expected_beats: int
    event: CanonicalEvent


@dataclass(frozen=True)
class JoinedToken:
    descriptor: DescriptorToken
    burst: BurstToken


@dataclass(frozen=True)
class FifoJoinState:
    descriptors: tuple[DescriptorToken, ...] = ()
    bursts: tuple[BurstToken, ...] = ()
    next_descriptor_serial: int = 0


@dataclass(frozen=True)
class FifoJoin:
    name: str
    count_of: Callable[[CanonicalEvent], int]
    data_rule: Callable[[CanonicalEvent, int, CanonicalEvent], str | None] | None = None
    data_rule_name: str = "data_relation"

    def __post_init__(self) -> None:
        if not self.name or not self.data_rule_name:
            raise ValueError("FIFO join requires a name and data-rule name")

    def initial_state(self) -> FifoJoinState:
        return FifoJoinState()

    def is_quiescent(self, state: FifoJoinState) -> bool:
        return not state.descriptors and not state.bursts

    def _drain(
        self, state: FifoJoinState
    ) -> SemanticStep[FifoJoinState, JoinedToken]:
        descriptors = list(state.descriptors)
        bursts = list(state.bursts)
        joined = []
        while descriptors and bursts:
            descriptor = descriptors[0]
            burst = bursts[0]
            if len(burst.events) != descriptor.expected_beats:
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.beat_count",
                        f"descriptor key {descriptor.key!r} requires "
                        f"{descriptor.expected_beats} beats, got {len(burst.events)}",
                        ConstraintScope.LINK,
                    ),
                )
            if self.data_rule is not None:
                for index, event in enumerate(burst.events):
                    reason = self.data_rule(descriptor.event, index, event)
                    if reason is not None:
                        return SemanticStep(
                            state,
                            fault=SemanticFault(
                                f"{self.name}.{self.data_rule_name}",
                                reason,
                                ConstraintScope.LINK,
                            ),
                        )
            descriptors.pop(0)
            bursts.pop(0)
            joined.append(JoinedToken(descriptor, burst))
        return SemanticStep(
            FifoJoinState(
                tuple(descriptors), tuple(bursts), state.next_descriptor_serial
            ),
            tuple(joined),
        )

    def add_descriptor(
        self, state: FifoJoinState, event: CanonicalEvent
    ) -> SemanticStep[FifoJoinState, JoinedToken]:
        expected = self.count_of(event)
        if type(expected) is not int or expected <= 0:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.count",
                    f"descriptor produced invalid beat count {expected!r}",
                    ConstraintScope.LINK,
                ),
            )
        descriptor = DescriptorToken(
            state.next_descriptor_serial, event.key, expected, event
        )
        return self._drain(
            FifoJoinState(
                state.descriptors + (descriptor,),
                state.bursts,
                state.next_descriptor_serial + 1,
            )
        )

    def add_burst(
        self, state: FifoJoinState, burst: BurstToken
    ) -> SemanticStep[FifoJoinState, JoinedToken]:
        return self._drain(
            FifoJoinState(
                state.descriptors,
                state.bursts + (burst,),
                state.next_descriptor_serial,
            )
        )


@dataclass(frozen=True)
class CompletionLedgerState:
    pending: tuple[JoinedToken, ...] = ()


@dataclass(frozen=True)
class CompletionLedger:
    name: str
    completion_kind: str

    def initial_state(self) -> CompletionLedgerState:
        return CompletionLedgerState()

    def is_quiescent(self, state: CompletionLedgerState) -> bool:
        return not state.pending

    def add(
        self, state: CompletionLedgerState, tokens: tuple[JoinedToken, ...]
    ) -> CompletionLedgerState:
        return CompletionLedgerState(state.pending + tokens)

    def event_offers(self, state: CompletionLedgerState) -> tuple[EventOffer, ...]:
        offers = []
        seen_keys = set()
        for token in state.pending:
            key = token.descriptor.key
            if key in seen_keys:
                continue
            seen_keys.add(key)
            offers.append(EventOffer.constrained(self.completion_kind, key=key))
        return tuple(offers)

    def consume(
        self, state: CompletionLedgerState, event: CanonicalEvent
    ) -> SemanticStep[CompletionLedgerState, JoinedToken]:
        index = next(
            (
                index
                for index, token in enumerate(state.pending)
                if token.descriptor.key == event.key
            ),
            None,
        )
        if index is None:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.orphan_completion",
                    f"completion key {event.key!r} has no joined transaction",
                    ConstraintScope.LINK,
                ),
            )
        token = state.pending[index]
        pending = list(state.pending)
        del pending[index]
        predecessors = (
            token.descriptor.event.trace_index,
            token.burst.events[-1].trace_index,
        )
        return SemanticStep(
            CompletionLedgerState(tuple(pending)),
            (token,),
            causal_predecessors=tuple(
                item for item in predecessors if item is not None
            ),
        )
