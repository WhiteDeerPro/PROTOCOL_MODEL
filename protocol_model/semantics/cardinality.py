"""Keyed cardinality obligations for multibeat protocol transactions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random
from typing import Callable, Hashable

from protocol_model.domains import EventSpace
from protocol_model.core import CanonicalEvent, SemanticComponent, SemanticFault, SemanticStep


@dataclass(frozen=True)
class CardinalityToken:
    serial: int
    key: Hashable
    total: int
    remaining: int
    origin: CanonicalEvent
    previous_beat: CanonicalEvent | None = None


@dataclass(frozen=True)
class CardinalityState:
    pending: tuple[CardinalityToken, ...] = ()
    next_serial: int = 0


@dataclass(frozen=True)
class CardinalityObligation(
    SemanticComponent[CanonicalEvent, CardinalityState, CanonicalEvent]
):
    """A colored FIFO of exact-count completion obligations.

    Each ``begin`` event creates a token colored by transaction key. Beat
    events consume the oldest token of the same color. The configured final
    marker must be false before the last beat and true exactly on the last.
    """

    name: str
    begin: EventSpace
    beat: EventSpace
    count_of: Callable[[CanonicalEvent], int]
    final_field: str = "last"

    def __post_init__(self) -> None:
        if self.begin.kind == self.beat.kind:
            raise ValueError("begin and beat event kinds must differ")
        if self.final_field not in self.beat.payload:
            raise ValueError(f"beat EventSpace has no {self.final_field!r} field")

    def initial_state(self) -> CardinalityState:
        return CardinalityState()

    def is_quiescent(self, state: CardinalityState) -> bool:
        return not state.pending

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in {self.begin.kind, self.beat.kind}

    def _causal_predecessors(
        self, state: CardinalityState, event: CanonicalEvent
    ) -> tuple[int, ...]:
        if event.kind != self.beat.kind:
            return ()
        token = next((item for item in state.pending if item.key == event.key), None)
        if token is None:
            return ()
        predecessor = token.previous_beat or token.origin
        return () if predecessor.trace_index is None else (predecessor.trace_index,)

    def _fault(self, state: CardinalityState, rule: str, reason: str) -> SemanticStep:
        return SemanticStep(state, fault=SemanticFault(f"{self.name}.{rule}", reason))

    def step(
        self, state: CardinalityState, event: CanonicalEvent
    ) -> SemanticStep[CardinalityState, CanonicalEvent]:
        if event.kind == self.begin.kind:
            reasons = self.begin.explain(event)
            if reasons:
                return self._fault(state, "begin_space", "; ".join(reasons))
            count = self.count_of(event)
            if type(count) is not int or count <= 0:
                return self._fault(
                    state, "count", f"begin event produced invalid beat count {count!r}"
                )
            token = CardinalityToken(state.next_serial, event.key, count, count, event)
            return SemanticStep(
                CardinalityState(state.pending + (token,), state.next_serial + 1),
                (event,),
            )

        if event.kind != self.beat.kind:
            return self._fault(
                state,
                "alphabet",
                f"expected {self.begin.kind!r} or {self.beat.kind!r}, got {event.kind!r}",
            )
        reasons = self.beat.explain(event)
        if reasons:
            return self._fault(state, "beat_space", "; ".join(reasons))
        token_index = next(
            (index for index, token in enumerate(state.pending) if token.key == event.key),
            None,
        )
        if token_index is None:
            return self._fault(
                state, "orphan_beat", f"beat for key {event.key!r} has no pending obligation"
            )
        token = state.pending[token_index]
        expected_final = token.remaining == 1
        observed_final = event.payload[self.final_field]
        if observed_final is not expected_final:
            position = token.total - token.remaining + 1
            return self._fault(
                state,
                "final_marker",
                f"beat {position}/{token.total} for key {token.key!r} "
                f"requires {self.final_field}={expected_final}, got {observed_final!r}",
            )
        pending = list(state.pending)
        if expected_final:
            del pending[token_index]
        else:
            pending[token_index] = replace(
                token, remaining=token.remaining - 1, previous_beat=event
            )
        return SemanticStep(
            CardinalityState(tuple(pending), state.next_serial),
            (event,),
            causal_predecessors=self._causal_predecessors(state, event),
        )

    def sample_legal(
        self,
        state: CardinalityState,
        rng: Random,
        *,
        allow_begin: bool = True,
        begin_probability: float = 0.35,
    ) -> CanonicalEvent:
        if not 0.0 <= begin_probability <= 1.0:
            raise ValueError("begin_probability must be in [0, 1]")
        if allow_begin and (not state.pending or rng.random() < begin_probability):
            return self.begin.sample(rng)
        if not state.pending:
            raise ValueError("no pending cardinality token from which to sample a beat")
        token = rng.choice(state.pending)
        return self.beat.sample_constrained(
            rng,
            key=token.key,
            payload={self.final_field: token.remaining == 1},
        )
