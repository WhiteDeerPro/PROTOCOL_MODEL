"""Protocol-visible inputs, emissions, effects, and local transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import CanonicalEvent, SemanticFault


@dataclass(frozen=True)
class DutEffect:
    """One protocol-independent effect passed between behaviors inside a DUT."""

    kind: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("DUT effect requires a kind")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class PortInput:
    port: str
    event: CanonicalEvent


@dataclass(frozen=True)
class PortEmission:
    port: str
    event: CanonicalEvent


@dataclass(frozen=True)
class DutTransition:
    state: object
    emissions: tuple[PortEmission, ...] = ()
    fault: SemanticFault | None = None
