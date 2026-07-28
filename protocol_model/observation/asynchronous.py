"""Ordered observation points that do not claim a shared sampling clock."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class AsynchronousSample:
    """One ordered, edge-complete snapshot of asynchronous interface signals.

    ``sequence`` is observation order, not a clock cycle.  ``timestamp`` is
    optional evidence supplied by the trace source and need not use a project-
    wide time unit.  An observer may require every relevant signal transition
    to appear in this sequence; this assumption must be satisfied by the trace
    importer or formal harness.
    """

    sequence: int
    observations: Mapping[str, object] = field(default_factory=dict)
    timestamp: int | float | None = None
    source: str = "trace"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ValueError("asynchronous sample sequence must be non-negative")
        if self.timestamp is not None and (
            not isinstance(self.timestamp, (int, float))
            or isinstance(self.timestamp, bool)
        ):
            raise TypeError("asynchronous sample timestamp must be numeric or None")
        if not self.source:
            raise ValueError("asynchronous sample requires a source")
        observations = dict(self.observations)
        if any(not name for name in observations):
            raise ValueError("observation names must not be empty")
        object.__setattr__(
            self, "observations", MappingProxyType(observations)
        )

    def get(self, name: str):
        return self.observations[name]


__all__ = ["AsynchronousSample"]
