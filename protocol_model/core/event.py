"""Canonical semantic event shared by every protocol model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Mapping


@dataclass(frozen=True)
class CanonicalEvent:
    kind: str
    key: Hashable
    payload: Mapping[str, object] = field(default_factory=dict)
    source: str = "model"
    clock: str | None = None
    timestamp: int | float | None = None
    sequence: int | None = None
    trace_index: int | None = None

    def short(self) -> str:
        fields = ", ".join(f"{name}={value!r}" for name, value in self.payload.items())
        suffix = f", {fields}" if fields else ""
        return f"{self.kind}(key={self.key!r}{suffix})"
