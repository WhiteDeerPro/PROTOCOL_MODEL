"""Keyed exact-count obligations for request/response and multibeat links."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
class CardinalityToken:
    serial: int
    key: Hashable
    total: int
    remaining: int
    origin_index: int
    previous_index: int | None = None


@dataclass(frozen=True)
class CardinalityState:
    pending: tuple[CardinalityToken, ...] = ()
    next_serial: int = 0


@dataclass(frozen=True)
class CardinalityMonitor(
    SemanticComponent[CanonicalEvent, CardinalityState, object]
):
    """Each begin event opens an exact number of keyed completion beats."""

    name: str
    begin_kind: str
    beat_kind: str
    count_of: Callable[[CanonicalEvent], int]
    final_field: str | None = None
    resource_name: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.begin_kind or not self.beat_kind:
            raise ValueError("cardinality monitor requires name and event kinds")
        if self.begin_kind == self.beat_kind:
            raise ValueError("begin and beat event kinds must differ")

    def initial_state(self) -> CardinalityState:
        return CardinalityState()

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in {self.begin_kind, self.beat_kind}

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset((self.begin_kind, self.beat_kind))

    def event_offers(self, state: CardinalityState) -> tuple[EventOffer, ...]:
        """Expose begins and the next legal beat for each active key."""

        offers = [EventOffer.unconstrained(self.begin_kind)]
        seen_keys = set()
        for token in state.pending:
            if token.key in seen_keys:
                continue
            seen_keys.add(token.key)
            payload = (
                {}
                if self.final_field is None
                else {self.final_field: token.remaining == 1}
            )
            offers.append(
                EventOffer.constrained(
                    self.beat_kind, key=token.key, payload=payload
                )
            )
        return tuple(offers)

    def is_quiescent(self, state: CardinalityState) -> bool:
        return not state.pending

    def resource_usage(self, state: CardinalityState) -> dict[str, int]:
        if self.resource_name is None:
            return {}
        return {self.resource_name: len(state.pending)}

    def _fault(
        self, state: CardinalityState, rule: str, reason: str
    ) -> SemanticStep[CardinalityState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    def step(
        self, state: CardinalityState, event: CanonicalEvent
    ) -> SemanticStep[CardinalityState, object]:
        if event.trace_index is None:
            return self._fault(
                state,
                "trace_index",
                "cardinality events must be normalized by a LinkSession",
            )
        if event.kind == self.begin_kind:
            count = self.count_of(event)
            if type(count) is not int or count <= 0:
                return self._fault(
                    state,
                    "count",
                    f"begin event produced invalid completion count {count!r}",
                )
            token = CardinalityToken(
                state.next_serial,
                event.key,
                count,
                count,
                event.trace_index,
            )
            return SemanticStep(
                CardinalityState(state.pending + (token,), state.next_serial + 1)
            )
        if event.kind != self.beat_kind:
            return self._fault(
                state, "alphabet", f"unexpected event kind {event.kind!r}"
            )
        token_index = next(
            (
                index
                for index, token in enumerate(state.pending)
                if token.key == event.key
            ),
            None,
        )
        if token_index is None:
            return self._fault(
                state,
                "orphan_beat",
                f"completion for key {event.key!r} has no pending obligation",
            )
        token = state.pending[token_index]
        expected_final = token.remaining == 1
        if self.final_field is not None:
            if self.final_field not in event.payload:
                return self._fault(
                    state,
                    "final_field",
                    f"completion has no {self.final_field!r} field",
                )
            observed_final = event.payload[self.final_field]
            if observed_final is not expected_final:
                position = token.total - token.remaining + 1
                return self._fault(
                    state,
                    "final_marker",
                    f"beat {position}/{token.total} for key {token.key!r} requires "
                    f"{self.final_field}={expected_final}, got {observed_final!r}",
                )

        predecessor = (
            token.previous_index
            if token.previous_index is not None
            else token.origin_index
        )
        pending = list(state.pending)
        if expected_final:
            del pending[token_index]
        else:
            pending[token_index] = replace(
                token,
                remaining=token.remaining - 1,
                previous_index=event.trace_index,
            )
        return SemanticStep(
            CardinalityState(tuple(pending), state.next_serial),
            causal_predecessors=(predecessor,),
        )
