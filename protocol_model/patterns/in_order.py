"""Strict FIFO request/completion correlation without transaction IDs."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Hashable, Mapping

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


@dataclass(frozen=True)
class InOrderToken:
    serial: int
    request_kind: str
    completion_kind: str
    key: Hashable
    origin_index: int


@dataclass(frozen=True)
class InOrderState:
    pending: tuple[InOrderToken, ...] = ()
    next_serial: int = 0


@dataclass(frozen=True)
class InOrderCompletionMonitor(
    SemanticComponent[CanonicalEvent, InOrderState, InOrderToken]
):
    """Map request kinds to completion kinds and consume strictly in order."""

    name: str
    completions: Mapping[str, str]
    resource_name: str | None = None
    maximum_pending: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("in-order completion monitor requires a name")
        completions = dict(self.completions)
        if not completions or any(not request or not reply for request, reply in completions.items()):
            raise ValueError("request/completion mapping must not be empty")
        if set(completions) & set(completions.values()):
            raise ValueError("request and completion event kinds must be distinct")
        if self.maximum_pending is not None and self.maximum_pending <= 0:
            raise ValueError("maximum pending count must be positive")
        object.__setattr__(self, "completions", MappingProxyType(completions))

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset((*self.completions, *self.completions.values()))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> InOrderState:
        return InOrderState()

    def is_quiescent(self, state: InOrderState) -> bool:
        return not state.pending

    def resource_usage(self, state: InOrderState) -> dict[str, int]:
        if self.resource_name is None:
            return {}
        return {self.resource_name: len(state.pending)}

    def event_offers(self, state: InOrderState) -> tuple[EventOffer, ...]:
        offers = []
        if self.maximum_pending is None or len(state.pending) < self.maximum_pending:
            offers.extend(EventOffer.unconstrained(kind) for kind in self.completions)
        if state.pending:
            token = state.pending[0]
            offers.append(
                EventOffer.constrained(token.completion_kind, key=token.key)
            )
        return tuple(offers)

    def _fault(
        self, state: InOrderState, rule: str, reason: str
    ) -> SemanticStep[InOrderState, InOrderToken]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    def step(
        self, state: InOrderState, event: CanonicalEvent
    ) -> SemanticStep[InOrderState, InOrderToken]:
        if event.trace_index is None:
            return self._fault(
                state,
                "trace_index",
                "request/completion events must be normalized by a LinkSession",
            )
        if event.kind in self.completions:
            if (
                self.maximum_pending is not None
                and len(state.pending) >= self.maximum_pending
            ):
                return self._fault(
                    state,
                    "capacity",
                    f"pending request count reached {self.maximum_pending}",
                )
            token = InOrderToken(
                state.next_serial,
                event.kind,
                self.completions[event.kind],
                event.key,
                event.trace_index,
            )
            return SemanticStep(
                InOrderState(
                    state.pending + (token,), state.next_serial + 1
                )
            )
        if event.kind not in self.completions.values():
            return self._fault(
                state, "alphabet", f"unexpected event kind {event.kind!r}"
            )
        if not state.pending:
            return self._fault(
                state,
                "orphan_completion",
                f"{event.kind} has no pending request",
            )
        token = state.pending[0]
        if event.kind != token.completion_kind:
            return self._fault(
                state,
                "completion_order",
                f"oldest {token.request_kind} requires {token.completion_kind}, "
                f"got {event.kind}",
            )
        if event.key != token.key:
            return self._fault(
                state,
                "completion_key",
                f"oldest request key {token.key!r}, got {event.key!r}",
            )
        return SemanticStep(
            InOrderState(state.pending[1:], state.next_serial),
            (token,),
            causal_predecessors=(token.origin_index,),
        )
