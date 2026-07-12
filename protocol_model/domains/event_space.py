"""A symbolic canonical-event schema with shared sampling and membership."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from types import MappingProxyType
from typing import Callable, Mapping

from protocol_model.core import CanonicalEvent

from .values import ValueDomain


_UNSET = object()


@dataclass(frozen=True)
class EventConstraint:
    name: str
    predicate: Callable[[CanonicalEvent], bool]
    reason: str


@dataclass(frozen=True)
class EventSpace:
    kind: str
    key: ValueDomain
    payload: Mapping[str, ValueDomain]
    constraints: tuple[EventConstraint, ...] = ()
    allow_extra_payload: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def sample(self, rng: Random, *, max_attempts: int = 10_000) -> CanonicalEvent:
        return self.sample_constrained(rng, max_attempts=max_attempts)

    def sample_constrained(
        self,
        rng: Random,
        *,
        key=_UNSET,
        payload: Mapping[str, object] | None = None,
        max_attempts: int = 10_000,
    ) -> CanonicalEvent:
        """Sample while fixing selected fields, then apply the same constraints."""

        payload = dict(payload or {})
        unknown = set(payload) - set(self.payload)
        if unknown:
            raise ValueError(f"unknown constrained payload fields {sorted(unknown)}")
        if key is not _UNSET:
            reason = self.key.explain(key)
            if reason:
                raise ValueError(f"constrained key: {reason}")
        for name, value in payload.items():
            reason = self.payload[name].explain(value)
            if reason:
                raise ValueError(f"constrained payload.{name}: {reason}")
        for _ in range(max_attempts):
            event = CanonicalEvent(
                self.kind,
                self.key.sample(rng) if key is _UNSET else key,
                {
                    name: payload[name] if name in payload else domain.sample(rng)
                    for name, domain in self.payload.items()
                },
            )
            if self.contains(event):
                return event
        raise RuntimeError(
            f"failed to sample {self.kind!r} after {max_attempts} attempts; "
            "constraints may be unsatisfiable or sampling may need a constructive policy"
        )

    def contains(self, event: CanonicalEvent) -> bool:
        return not self.explain(event)

    def explain(self, event: CanonicalEvent) -> tuple[str, ...]:
        reasons: list[str] = []
        if event.kind != self.kind:
            reasons.append(f"expected event kind {self.kind!r}, got {event.kind!r}")
            return tuple(reasons)
        key_reason = self.key.explain(event.key)
        if key_reason:
            reasons.append(f"key: {key_reason}")
        missing = set(self.payload) - set(event.payload)
        if missing:
            reasons.append(f"missing payload fields {sorted(missing)}")
        if not self.allow_extra_payload:
            extra = set(event.payload) - set(self.payload)
            if extra:
                reasons.append(f"unexpected payload fields {sorted(extra)}")
        for name, domain in self.payload.items():
            if name not in event.payload:
                continue
            reason = domain.explain(event.payload[name])
            if reason:
                reasons.append(f"payload.{name}: {reason}")
        if not reasons:
            reasons.extend(
                constraint.reason
                for constraint in self.constraints
                if not constraint.predicate(event)
            )
        return tuple(reasons)
