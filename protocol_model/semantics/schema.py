"""Schemas for concrete :class:`CanonicalEvent` values."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from types import MappingProxyType
from typing import Mapping

from .event import (
    CanonicalEvent,
    ConstantDomain,
    EventConstraint,
    ValueDomain,
)
from .generation import EventOffer


@dataclass(frozen=True)
class EventField:
    """One named payload field in an event schema."""

    name: str
    domain: ValueDomain
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("event field requires a name")


@dataclass(frozen=True)
class EventSchema:
    """A scope-neutral schema for one canonical event kind."""

    name: str
    fields: Mapping[str, EventField] = field(default_factory=dict)
    key: ValueDomain = field(default_factory=lambda: ConstantDomain(None))
    constraints: tuple[EventConstraint, ...] = ()
    allow_extra_fields: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("event schema requires a name")
        fields = dict(self.fields)
        if set(fields) != {item.name for item in fields.values()}:
            raise ValueError("event field mapping keys must match field names")
        object.__setattr__(self, "fields", MappingProxyType(fields))

    def explain(self, event: CanonicalEvent) -> tuple[str, ...]:
        reasons: list[str] = []
        if event.kind != self.name:
            return (f"expected event kind {self.name!r}, got {event.kind!r}",)
        key_reason = self.key.explain(event.key)
        if key_reason:
            reasons.append(f"key: {key_reason}")
        missing = set(self.fields) - set(event.payload)
        if missing:
            reasons.append(f"missing payload fields {sorted(missing)!r}")
        if not self.allow_extra_fields:
            extra = set(event.payload) - set(self.fields)
            if extra:
                reasons.append(f"unexpected payload fields {sorted(extra)!r}")
        for name, event_field in self.fields.items():
            if name not in event.payload:
                continue
            reason = event_field.domain.explain(event.payload[name])
            if reason:
                reasons.append(f"payload.{name}: {reason}")
        if not reasons:
            reasons.extend(
                constraint.reason
                for constraint in self.constraints
                if not constraint.predicate(event)
            )
        return tuple(reasons)

    def contains(self, event: CanonicalEvent) -> bool:
        return not self.explain(event)

    def generate(
        self,
        rng: Random,
        offer: EventOffer | None = None,
        *,
        max_attempts: int = 10_000,
    ) -> CanonicalEvent:
        """Complete a partial enabled offer and validate the result."""

        offer = offer or EventOffer.unconstrained(self.name)
        if offer.kind != self.name:
            raise ValueError(
                f"offer kind {offer.kind!r} does not match schema {self.name!r}"
            )
        unknown = set(offer.payload) - set(self.fields)
        if unknown:
            raise ValueError(f"offer fixes unknown fields {sorted(unknown)!r}")
        if offer.key_is_set:
            reason = self.key.explain(offer.key)
            if reason:
                raise ValueError(f"offered key: {reason}")
        for name, value in offer.payload.items():
            reason = self.fields[name].domain.explain(value)
            if reason:
                raise ValueError(f"offered payload.{name}: {reason}")
        for _ in range(max_attempts):
            event = CanonicalEvent(
                self.name,
                offer.key if offer.key_is_set else self.key.sample(rng),
                {
                    name: (
                        offer.payload[name]
                        if name in offer.payload
                        else event_field.domain.sample(rng)
                    )
                    for name, event_field in self.fields.items()
                },
            )
            if self.contains(event):
                return event
        raise RuntimeError(
            f"failed to sample event {self.name!r}; constraints may be unsatisfiable"
        )

    def sample(self, rng: Random, *, max_attempts: int = 10_000) -> CanonicalEvent:
        return self.generate(rng, max_attempts=max_attempts)


__all__ = ["EventField", "EventSchema"]
