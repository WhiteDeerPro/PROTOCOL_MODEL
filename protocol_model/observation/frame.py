"""Clocked observations grouped by sampling instant."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class AtomicFrame:
    """All interface observations taken at one edge of one clock.

    The frame preserves simultaneity. It does not decide whether any signal
    behavior is legal; protocol-specific observers make that decision.
    """

    tick: int
    clock: str
    observations: Mapping[str, object] = field(default_factory=dict)
    source: str = "trace"

    def __post_init__(self) -> None:
        if not isinstance(self.tick, int) or isinstance(self.tick, bool):
            raise TypeError("frame tick must be an integer")
        if self.tick < 0:
            raise ValueError("frame tick must be non-negative")
        if not self.clock:
            raise ValueError("atomic frame requires a clock")
        observations = dict(self.observations)
        if any(not name for name in observations):
            raise ValueError("observation names must not be empty")
        object.__setattr__(self, "observations", MappingProxyType(observations))

    def get(self, name: str):
        return self.observations[name]
