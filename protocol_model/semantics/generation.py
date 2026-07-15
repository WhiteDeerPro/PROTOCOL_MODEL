"""Partial event assignments used by state-aware generators."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Hashable, Mapping


_UNSET = object()


@dataclass(frozen=True)
class EventOffer:
    """A currently enabled event kind with optional fixed fields.

    Offers are not events and are not accepted by protocol sessions. An
    EventSchema completes an offer into a concrete CanonicalEvent.
    """

    kind: str
    key: Hashable = None
    key_is_set: bool = False
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("event offer requires a kind")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @classmethod
    def unconstrained(cls, kind: str) -> "EventOffer":
        return cls(kind)

    @classmethod
    def constrained(
        cls,
        kind: str,
        *,
        key: Hashable | object = _UNSET,
        payload: Mapping[str, object] | None = None,
    ) -> "EventOffer":
        return cls(
            kind,
            None if key is _UNSET else key,  # type: ignore[arg-type]
            key is not _UNSET,
            payload or {},
        )

    def merge(self, other: "EventOffer") -> "EventOffer | None":
        if self.kind != other.kind:
            return None
        if self.key_is_set and other.key_is_set and self.key != other.key:
            return None
        payload = dict(self.payload)
        for name, value in other.payload.items():
            if name in payload and payload[name] != value:
                return None
            payload[name] = value
        key_is_set = self.key_is_set or other.key_is_set
        key = self.key if self.key_is_set else other.key
        return EventOffer(self.kind, key, key_is_set, payload)
