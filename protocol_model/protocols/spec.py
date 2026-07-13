"""Elaborated, immutable protocol-description IR."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.domains import EventSpace
from protocol_model.core import SemanticComponent
from protocol_model.patterns import ClockedReadyValid, ResetEpoch


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


@dataclass(frozen=True)
class ConstraintRecord:
    """Auditable constraint added when a Project configures a protocol."""

    name: str
    rule: str
    targets: tuple[str, ...]
    foundation: str
    scope: str = "PROFILE"

    def __post_init__(self) -> None:
        if not self.name or not self.rule or not self.targets:
            raise ValueError("constraint record requires name, rule, and targets")


@dataclass(frozen=True)
class ProtocolInstance:
    """One named use of a base or constrained protocol in a Project network."""

    name: str
    owner: str
    base_spec: ProtocolSpec
    spec: ProtocolSpec

    @classmethod
    def bind(
        cls,
        name: str,
        base_spec: ProtocolSpec,
        *,
        owner: str,
        constrained_spec: ProtocolSpec | None = None,
    ) -> "ProtocolInstance":
        if not name:
            raise ValueError("protocol instance needs a non-empty network name")
        if not owner:
            raise ValueError("protocol instance needs a non-empty Project owner")
        spec = constrained_spec or base_spec
        if (
            spec is not base_spec
            and spec.parameters.get("derived_from") != base_spec.name
        ):
            raise ValueError(
                f"constrained spec {spec.name!r} was not derived from "
                f"{base_spec.name!r}"
            )
        return cls(name, owner, base_spec, spec)

    @property
    def qualified_name(self) -> str:
        """Stable run identity; the short name only needs to be unique per Project."""

        return f"{self.owner}/{self.name}"

    @property
    def is_constrained(self) -> bool:
        return self.spec is not self.base_spec

    @property
    def constraints(self) -> tuple[ConstraintRecord, ...]:
        return tuple(self.spec.parameters.get("derivation_constraints", ()))

    def channel(self, name: str):
        return self.spec.channel(name)

    def open_session(self):
        return self.spec.open_session()


class ProtocolDerivation:
    """Elaboration builder for an immutable, Project-constrained protocol spec."""

    def __init__(self, base: ProtocolSpec, name: str):
        if not name or name == base.name:
            raise ValueError("derived protocol needs a distinct non-empty name")
        self.base = base
        self.name = name
        self.channels = dict(base.channels)
        self.models = dict(base.transaction_models)
        self.parameters = dict(base.parameters)
        self.records: list[ConstraintRecord] = []

    def replace_ready_valid_channel(
        self,
        name: str,
        transfer: EventSpace,
        *,
        clock: str = "aclk",
    ) -> "ProtocolDerivation":
        channel = self.channels[name]
        ready_valid = ClockedReadyValid(
            f"{name}.ready_valid", transfer, clock=clock
        )
        self.channels[name] = replace(
            channel,
            transfer=transfer,
            observation_model=ResetEpoch(
                f"{name}.reset_epoch",
                ready_valid,
                inactive=lambda sample: not sample.valid,
                inactive_reason=f"{name} VALID must be low while reset is asserted",
            ),
        )
        return self

    def replace_transaction_model(
        self, name: str, model
    ) -> "ProtocolDerivation":
        if name not in self.models:
            raise KeyError(f"unknown base transaction model {name!r}")
        self.models[name] = model
        return self

    def add_transaction_model(self, name: str, model) -> "ProtocolDerivation":
        if name in self.models:
            raise ValueError(f"transaction model {name!r} already exists")
        self.models[name] = model
        return self

    def constrain(self, record: ConstraintRecord) -> "ProtocolDerivation":
        if any(item.name == record.name for item in self.records):
            raise ValueError(f"constraint {record.name!r} already exists")
        channel_names = set(self.channels)
        for target in record.targets:
            prefix = target.split(".", 1)[0]
            if prefix not in channel_names and prefix not in {
                "interface",
                "transaction",
            }:
                raise ValueError(f"constraint target {target!r} is not declared")
        self.records.append(record)
        return self

    def set_parameter(self, name: str, value) -> "ProtocolDerivation":
        self.parameters[name] = value
        return self

    def build(self) -> ProtocolSpec:
        requirements = self.base.requirements + tuple(
            ProtocolRequirement(
                item.name,
                item.rule,
                item.foundation,
                "implemented",
            )
            for item in self.records
        )
        parameters = {
            **self.parameters,
            "derived_from": self.base.name,
            "derivation_constraints": tuple(self.records),
        }
        return ProtocolSpec(
            self.name,
            self.base.roles,
            self.channels,
            requirements,
            parameters,
            self.models,
        )
