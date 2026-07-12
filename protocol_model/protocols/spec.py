"""Elaborated, immutable protocol-description IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.domains import EventSpace
from protocol_model.core import SemanticComponent


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    source_role: str
    destination_role: str
    transfer: EventSpace
    observation_model: SemanticComponent | None = None


@dataclass(frozen=True)
class ProtocolRequirement:
    name: str
    rule: str
    foundation: str
    status: str


@dataclass(frozen=True)
class ProtocolSpec:
    name: str
    roles: frozenset[str]
    channels: Mapping[str, ChannelSpec]
    requirements: tuple[ProtocolRequirement, ...]
    parameters: Mapping[str, object]
    transaction_models: Mapping[str, SemanticComponent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", MappingProxyType(dict(self.channels)))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(
            self, "transaction_models", MappingProxyType(dict(self.transaction_models))
        )
        if set(self.channels) != {channel.name for channel in self.channels.values()}:
            raise ValueError("channel mapping keys must equal ChannelSpec names")
        for channel in self.channels.values():
            if channel.source_role not in self.roles or channel.destination_role not in self.roles:
                raise ValueError(f"channel {channel.name} uses an unknown role")

    def channel(self, name: str) -> ChannelSpec:
        return self.channels[name]

    def open_session(self):
        from .session import ProtocolSession

        return ProtocolSession(self)

    @property
    def missing_foundations(self) -> frozenset[str]:
        return frozenset(
            item.foundation for item in self.requirements if item.status != "implemented"
        )
