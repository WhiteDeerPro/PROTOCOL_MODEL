"""Construction-time capability closure for CHI Issue H systems.

A high-level feature is a reusable definition that expands into participant,
path, dependency, and system obligations.  The resolver only consumes
explicit immutable facts.  It neither installs participant behavior nor
changes transport/router execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import product
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote

from ..participants.capability import (
    CHI_CLEAN_EVICT_HOME_CAPABILITIES,
    CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES,
    CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_UNIQUE_HOME_CAPABILITIES,
    CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
    CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
    CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES,
    CHI_HOME_READ_NO_SNP_NDERR_PRODUCE,
    CHI_HOME_COMP_DATA_PRODUCE,
    CHI_HOME_PCREDIT_GRANT,
    CHI_HOME_PCREDIT_RECLAIM,
    CHI_HOME_READ_NO_SNP_ACCEPT,
    CHI_HOME_READ_UNIQUE_NDERR_PRODUCE,
    CHI_HOME_RETRY_ACK_PRODUCE,
    CHI_REQUESTER_READ_NO_SNP_NDERR_ACCEPT,
    CHI_REQUESTER_COMP_DATA_ACCEPT,
    CHI_REQUESTER_PCREDIT_CONSUME,
    CHI_REQUESTER_PCREDIT_RETURN,
    CHI_REQUESTER_READ_NO_SNP_ISSUE,
    CHI_REQUESTER_READ_UNIQUE_NDERR_ACCEPT,
    CHI_REQUESTER_RETRY_ACK_ACCEPT,
    ChiCapabilityKey,
    ChiParticipantCapability,
)
from ..representation import ChiChannelKind


@dataclass(frozen=True, order=True)
class ChiFeatureKey:
    """Stable name for one composable CHI system feature."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.startswith(
            "chi.feature."
        ):
            raise ValueError(
                "CHI feature keys require a non-empty 'chi.feature.' name"
            )

    def __str__(self) -> str:
        return self.name


CHI_FEATURE_READ_NO_SNP = ChiFeatureKey("chi.feature.read_no_snp")
CHI_FEATURE_READ_NO_SNP_NDERR = ChiFeatureKey(
    "chi.feature.read_no_snp.nderr"
)
CHI_FEATURE_REQUEST_RETRY = ChiFeatureKey("chi.feature.request_retry")
CHI_FEATURE_CLEAN_READ_SHARED = ChiFeatureKey(
    "chi.feature.clean_read_shared"
)
CHI_FEATURE_CLEAN_READ_UNIQUE = ChiFeatureKey(
    "chi.feature.clean_read_unique"
)
CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR = ChiFeatureKey(
    "chi.feature.clean_read_unique.nderr"
)
CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY = ChiFeatureKey(
    "chi.feature.clean_read_unique.retry"
)
CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS = ChiFeatureKey(
    "chi.feature.clean_unique.clean_peers"
)
CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER = ChiFeatureKey(
    "chi.feature.clean_unique.shared_dirty_peer"
)
CHI_FEATURE_MAKE_UNIQUE = ChiFeatureKey("chi.feature.make_unique")
CHI_FEATURE_DIRTY_UNIQUE_TRANSFER = ChiFeatureKey(
    "chi.feature.dirty_unique_transfer"
)
CHI_FEATURE_DIRTY_WRITEBACK = ChiFeatureKey(
    "chi.feature.dirty_writeback"
)
CHI_FEATURE_CLEAN_EVICT = ChiFeatureKey(
    "chi.feature.clean_evict"
)
CHI_FEATURE_CLEAN_EVICT_RETRY = ChiFeatureKey(
    "chi.feature.clean_evict.retry"
)
CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY = ChiFeatureKey(
    "chi.feature.mesi_read_not_shared_dirty"
)
# A policy preset, not another protocol layer.  Clean ReadUnique is supplied
# transitively by the dirty-Unique feature dependency.
CHI_MESI_NO_SD_REQUIRED_FEATURES = frozenset(
    (
        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    )
)

CHI_PATH_TYPED_PROTOCOL = ChiCapabilityKey("chi.path.typed_protocol")
CHI_PATH_ROUTING_IDENTITY_PRESERVED = ChiCapabilityKey(
    "chi.path.routing_identity_preserved"
)
CHI_BASE_PATH_CAPABILITIES = frozenset(
    (
        CHI_PATH_TYPED_PROTOCOL,
        CHI_PATH_ROUTING_IDENTITY_PRESERVED,
    )
)
CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_read_shared.lifecycle"
)
CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_read_unique.lifecycle"
)
CHI_SYSTEM_CLEAN_READ_UNIQUE_NDERR_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_read_unique.nderr.lifecycle"
)
CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_read_unique.retry.lifecycle"
)
CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_unique.clean_peers.lifecycle"
)
CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_unique.shared_dirty_peer.lifecycle"
)
CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE = ChiCapabilityKey(
    "chi.system.make_unique.lifecycle"
)
CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE = ChiCapabilityKey(
    "chi.system.dirty_unique_transfer.lifecycle"
)
CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE = ChiCapabilityKey(
    "chi.system.dirty_writeback.lifecycle"
)
CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_evict.lifecycle"
)
CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE = ChiCapabilityKey(
    "chi.system.clean_evict.retry.lifecycle"
)
CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE = ChiCapabilityKey(
    "chi.system.mesi_read_not_shared_dirty.lifecycle"
)


@dataclass(frozen=True)
class ChiFlowCapability:
    """Evidence for one resolved participant-to-participant channel path."""

    name: str
    source: str
    target: str
    channel: ChiChannelKind
    provides: frozenset[ChiCapabilityKey] = CHI_BASE_PATH_CAPABILITIES
    connections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, subject in (
            (self.name, "name"),
            (self.source, "source"),
            (self.target, "target"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"CHI flow capability requires a {subject}")
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI flow capability requires a known protocol channel"
            ) from error
        try:
            provides = frozenset(self.provides)
        except TypeError as error:
            raise TypeError("CHI flow capabilities must be iterable") from error
        if any(not isinstance(item, ChiCapabilityKey) for item in provides):
            raise TypeError(
                "CHI flow capabilities require ChiCapabilityKey values"
            )
        connections = tuple(self.connections)
        if any(
            not isinstance(item, str) or not item for item in connections
        ):
            raise ValueError(
                "CHI flow connection evidence requires non-empty names"
            )
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "provides", provides)
        object.__setattr__(self, "connections", connections)


class ChiRoleCardinality(str, Enum):
    """How one abstract feature role is bound by a construction."""

    SINGLE = "single"
    FINITE_SET = "finite_set"


@dataclass(frozen=True)
class ChiRoleRequirement:
    role: str
    capabilities: frozenset[ChiCapabilityKey]
    cardinality: ChiRoleCardinality = ChiRoleCardinality.SINGLE
    minimum_members: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role:
            raise ValueError("CHI role requirement requires a role name")
        capabilities = frozenset(self.capabilities)
        if not capabilities or any(
            not isinstance(item, ChiCapabilityKey)
            for item in capabilities
        ):
            raise TypeError(
                "CHI role requirement needs ChiCapabilityKey values"
            )
        try:
            cardinality = ChiRoleCardinality(self.cardinality)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI role requirement has an unknown cardinality"
            ) from error
        if (
            not isinstance(self.minimum_members, int)
            or isinstance(self.minimum_members, bool)
            or self.minimum_members < 0
        ):
            raise ValueError(
                "CHI role requirement minimum_members must be a "
                "non-negative integer"
            )
        if (
            cardinality is ChiRoleCardinality.SINGLE
            and self.minimum_members != 1
        ):
            raise ValueError(
                "a single CHI role requires exactly one member"
            )
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "cardinality", cardinality)


@dataclass(frozen=True)
class ChiFlowRequirement:
    name: str
    source_role: str
    target_role: str
    channel: ChiChannelKind
    capabilities: frozenset[ChiCapabilityKey] = CHI_BASE_PATH_CAPABILITIES

    def __post_init__(self) -> None:
        for value, subject in (
            (self.name, "name"),
            (self.source_role, "source role"),
            (self.target_role, "target role"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"CHI flow requirement requires a {subject}"
                )
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI flow requirement requires a known protocol channel"
            ) from error
        capabilities = frozenset(self.capabilities)
        if any(
            not isinstance(item, ChiCapabilityKey)
            for item in capabilities
        ):
            raise TypeError(
                "CHI flow requirement needs ChiCapabilityKey values"
            )
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True)
class ChiFeatureDefinition:
    """Reusable expansion of one feature into atomic closure obligations."""

    key: ChiFeatureKey
    dependencies: frozenset[ChiFeatureKey] = frozenset()
    roles: tuple[ChiRoleRequirement, ...] = ()
    flows: tuple[ChiFlowRequirement, ...] = ()
    system_capabilities: frozenset[ChiCapabilityKey] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.key, ChiFeatureKey):
            raise TypeError("CHI feature definition requires ChiFeatureKey")
        dependencies = frozenset(self.dependencies)
        if any(not isinstance(item, ChiFeatureKey) for item in dependencies):
            raise TypeError("CHI feature dependencies require ChiFeatureKey")
        if self.key in dependencies:
            raise ValueError("CHI feature cannot depend on itself")
        roles = tuple(self.roles)
        flows = tuple(self.flows)
        if any(not isinstance(item, ChiRoleRequirement) for item in roles):
            raise TypeError(
                "CHI feature roles require ChiRoleRequirement values"
            )
        if any(not isinstance(item, ChiFlowRequirement) for item in flows):
            raise TypeError(
                "CHI feature flows require ChiFlowRequirement values"
            )
        if len({item.role for item in roles}) != len(roles):
            raise ValueError("CHI feature role requirements must be unique")
        if len({item.name for item in flows}) != len(flows):
            raise ValueError("CHI feature flow requirements must be unique")
        system_capabilities = frozenset(self.system_capabilities)
        if any(
            not isinstance(item, ChiCapabilityKey)
            for item in system_capabilities
        ):
            raise TypeError(
                "CHI system requirements need ChiCapabilityKey values"
            )
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "flows", flows)
        object.__setattr__(
            self, "system_capabilities", system_capabilities
        )


@dataclass(frozen=True)
class ChiFeatureCatalog:
    """An explicit immutable set of feature definitions."""

    definitions: Mapping[ChiFeatureKey, ChiFeatureDefinition]

    def __post_init__(self) -> None:
        definitions = dict(self.definitions)
        if set(definitions) != {item.key for item in definitions.values()}:
            raise ValueError(
                "CHI feature catalog keys must match definition keys"
            )
        unknown = {
            dependency
            for definition in definitions.values()
            for dependency in definition.dependencies
            if dependency not in definitions
        }
        if unknown:
            raise ValueError(
                "CHI feature catalog has unknown dependencies: "
                f"{sorted(str(item) for item in unknown)!r}"
            )
        self._check_cycles(definitions)
        object.__setattr__(
            self, "definitions", MappingProxyType(definitions)
        )

    def extend(
        self, *definitions: ChiFeatureDefinition
    ) -> "ChiFeatureCatalog":
        additions = dict(self.definitions)
        for definition in definitions:
            if not isinstance(definition, ChiFeatureDefinition):
                raise TypeError(
                    "CHI feature catalog extension requires definitions"
                )
            if definition.key in additions:
                raise ValueError(
                    f"CHI feature {definition.key} is already registered"
                )
            additions[definition.key] = definition
        return ChiFeatureCatalog(additions)

    @staticmethod
    def _check_cycles(
        definitions: Mapping[ChiFeatureKey, ChiFeatureDefinition],
    ) -> None:
        visiting: set[ChiFeatureKey] = set()
        visited: set[ChiFeatureKey] = set()

        def visit(key: ChiFeatureKey) -> None:
            if key in visited:
                return
            if key in visiting:
                raise ValueError(
                    f"CHI feature dependency cycle reaches {key}"
                )
            visiting.add(key)
            for dependency in definitions[key].dependencies:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in definitions:
            visit(key)


CHI_READ_NO_SNP_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_READ_NO_SNP,
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset(
                (
                    CHI_REQUESTER_READ_NO_SNP_ISSUE,
                    CHI_REQUESTER_COMP_DATA_ACCEPT,
                )
            ),
        ),
        ChiRoleRequirement(
            "home",
            frozenset(
                (
                    CHI_HOME_READ_NO_SNP_ACCEPT,
                    CHI_HOME_COMP_DATA_PRODUCE,
                )
            ),
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "completion_data",
            "home",
            "requester",
            ChiChannelKind.DAT,
        ),
    ),
)

CHI_READ_NO_SNP_NDERR_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_READ_NO_SNP_NDERR,
    dependencies=frozenset((CHI_FEATURE_READ_NO_SNP,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset((CHI_REQUESTER_READ_NO_SNP_NDERR_ACCEPT,)),
        ),
        ChiRoleRequirement(
            "home",
            frozenset((CHI_HOME_READ_NO_SNP_NDERR_PRODUCE,)),
        ),
    ),
)

CHI_REQUEST_RETRY_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_REQUEST_RETRY,
    dependencies=frozenset((CHI_FEATURE_READ_NO_SNP,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset(
                (
                    CHI_REQUESTER_RETRY_ACK_ACCEPT,
                    CHI_REQUESTER_PCREDIT_CONSUME,
                    CHI_REQUESTER_PCREDIT_RETURN,
                )
            ),
        ),
        ChiRoleRequirement(
            "home",
            frozenset(
                (
                    CHI_HOME_RETRY_ACK_PRODUCE,
                    CHI_HOME_PCREDIT_GRANT,
                    CHI_HOME_PCREDIT_RECLAIM,
                )
            ),
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "retry_response",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
    ),
)

CHI_CLEAN_READ_SHARED_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_READ_SHARED,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=0,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "snoop",
            "home",
            "snoopee",
            ChiChannelKind.SNP,
        ),
        ChiFlowRequirement(
            "snoop_response",
            "snoopee",
            "home",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "completion_data",
            "home",
            "requester",
            ChiChannelKind.DAT,
        ),
        ChiFlowRequirement(
            "completion_ack",
            "requester",
            "home",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE,)
    ),
)

CHI_CLEAN_READ_UNIQUE_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=0,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "snoop",
            "home",
            "snoopee",
            ChiChannelKind.SNP,
        ),
        ChiFlowRequirement(
            "snoop_response",
            "snoopee",
            "home",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "completion_data",
            "home",
            "requester",
            ChiChannelKind.DAT,
        ),
        ChiFlowRequirement(
            "completion_ack",
            "requester",
            "home",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
    ),
)

CHI_CLEAN_READ_UNIQUE_NDERR_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
    dependencies=frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset((CHI_REQUESTER_READ_UNIQUE_NDERR_ACCEPT,)),
        ),
        ChiRoleRequirement(
            "home",
            frozenset((CHI_HOME_READ_UNIQUE_NDERR_PRODUCE,)),
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_READ_UNIQUE_NDERR_LIFECYCLE,)
    ),
)

CHI_CLEAN_READ_UNIQUE_RETRY_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    dependencies=frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset(
                (
                    CHI_REQUESTER_RETRY_ACK_ACCEPT,
                    CHI_REQUESTER_PCREDIT_CONSUME,
                )
            ),
        ),
        ChiRoleRequirement(
            "home",
            frozenset(
                (
                    CHI_HOME_RETRY_ACK_PRODUCE,
                    CHI_HOME_PCREDIT_GRANT,
                )
            ),
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "retry_response",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,)
    ),
)

CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=0,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "clean_unique_request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "clean_unique_snoop",
            "home",
            "snoopee",
            ChiChannelKind.SNP,
        ),
        ChiFlowRequirement(
            "clean_unique_snoop_response",
            "snoopee",
            "home",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "clean_unique_completion",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "clean_unique_completion_ack",
            "requester",
            "home",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,)
    ),
)

CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    dependencies=frozenset((CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,)),
    roles=(
        ChiRoleRequirement(
            "home",
            CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=1,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "clean_unique_snoop_data",
            "snoopee",
            "home",
            ChiChannelKind.DAT,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,)
    ),
)

CHI_MAKE_UNIQUE_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_MAKE_UNIQUE,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=0,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "make_unique_request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "make_unique_snoop",
            "home",
            "snoopee",
            ChiChannelKind.SNP,
        ),
        ChiFlowRequirement(
            "make_unique_snoop_response",
            "snoopee",
            "home",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "make_unique_completion",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "make_unique_completion_ack",
            "requester",
            "home",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE,)
    ),
)

CHI_DIRTY_UNIQUE_TRANSFER_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    dependencies=frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_DIRTY_UNIQUE_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=1,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "dirty_snoop_data",
            "snoopee",
            "home",
            ChiChannelKind.DAT,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,)
    ),
)

# A dirty victim must already be held with Unique authority.  That is a
# participant-state precondition, not proof that this same construction can
# acquire the line through ReadUnique.  Keeping writeback independent permits
# a cache seeded or filled through another local/interface path and avoids
# inventing an unused Snoopee flow.
CHI_DIRTY_WRITEBACK_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_DIRTY_WRITEBACK,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "writeback_request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "writeback_dbid_response",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "writeback_copyback_data",
            "requester",
            "home",
            ChiChannelKind.DAT,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,)
    ),
)

CHI_CLEAN_EVICT_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_EVICT,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_CLEAN_EVICT_HOME_CAPABILITIES,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "evict_request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "evict_completion",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,)
    ),
)

CHI_CLEAN_EVICT_RETRY_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_CLEAN_EVICT_RETRY,
    dependencies=frozenset((CHI_FEATURE_CLEAN_EVICT,)),
    roles=(
        ChiRoleRequirement(
            "requester",
            frozenset(
                (
                    CHI_REQUESTER_RETRY_ACK_ACCEPT,
                    CHI_REQUESTER_PCREDIT_CONSUME,
                )
            ),
        ),
        ChiRoleRequirement(
            "home",
            frozenset(
                (
                    CHI_HOME_RETRY_ACK_PRODUCE,
                    CHI_HOME_PCREDIT_GRANT,
                )
            ),
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "retry_response",
            "home",
            "requester",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE,)
    ),
)

CHI_MESI_READ_NOT_SHARED_DIRTY_DEFINITION = ChiFeatureDefinition(
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    roles=(
        ChiRoleRequirement(
            "requester",
            CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "home",
            CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES,
        ),
        ChiRoleRequirement(
            "snoopee",
            CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES,
            ChiRoleCardinality.FINITE_SET,
            minimum_members=1,
        ),
    ),
    flows=(
        ChiFlowRequirement(
            "mesi_read_request",
            "requester",
            "home",
            ChiChannelKind.REQ,
        ),
        ChiFlowRequirement(
            "mesi_read_snoop",
            "home",
            "snoopee",
            ChiChannelKind.SNP,
        ),
        ChiFlowRequirement(
            "mesi_read_snoop_response",
            "snoopee",
            "home",
            ChiChannelKind.RSP,
        ),
        ChiFlowRequirement(
            "mesi_read_snoop_data",
            "snoopee",
            "home",
            ChiChannelKind.DAT,
        ),
        ChiFlowRequirement(
            "mesi_read_completion_data",
            "home",
            "requester",
            ChiChannelKind.DAT,
        ),
        ChiFlowRequirement(
            "mesi_read_completion_ack",
            "requester",
            "home",
            ChiChannelKind.RSP,
        ),
    ),
    system_capabilities=frozenset(
        (CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE,)
    ),
)

CHI_BUILTIN_FEATURE_CATALOG = ChiFeatureCatalog(
    {
        CHI_FEATURE_READ_NO_SNP: CHI_READ_NO_SNP_DEFINITION,
        CHI_FEATURE_READ_NO_SNP_NDERR: CHI_READ_NO_SNP_NDERR_DEFINITION,
        CHI_FEATURE_REQUEST_RETRY: CHI_REQUEST_RETRY_DEFINITION,
        CHI_FEATURE_CLEAN_READ_SHARED: CHI_CLEAN_READ_SHARED_DEFINITION,
        CHI_FEATURE_CLEAN_READ_UNIQUE: CHI_CLEAN_READ_UNIQUE_DEFINITION,
        CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR: (
            CHI_CLEAN_READ_UNIQUE_NDERR_DEFINITION
        ),
        CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY: (
            CHI_CLEAN_READ_UNIQUE_RETRY_DEFINITION
        ),
        CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS: (
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION
        ),
        CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER: (
            CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION
        ),
        CHI_FEATURE_MAKE_UNIQUE: CHI_MAKE_UNIQUE_DEFINITION,
        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER: (
            CHI_DIRTY_UNIQUE_TRANSFER_DEFINITION
        ),
        CHI_FEATURE_DIRTY_WRITEBACK: CHI_DIRTY_WRITEBACK_DEFINITION,
        CHI_FEATURE_CLEAN_EVICT: CHI_CLEAN_EVICT_DEFINITION,
        CHI_FEATURE_CLEAN_EVICT_RETRY: CHI_CLEAN_EVICT_RETRY_DEFINITION,
        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY: (
            CHI_MESI_READ_NOT_SHARED_DIRTY_DEFINITION
        ),
    }
)


@dataclass(frozen=True)
class ChiFeatureContract:
    """Role assignment and features required by one CHI construction.

    ``roles`` binds ordinary one-participant roles.  ``role_sets`` binds an
    explicitly finite construction domain, such as all peer Snoopees whose
    SNP/RSP reachability must be proven.  A scalar binding can still satisfy a
    finite-set requirement as the natural singleton case.
    """

    roles: Mapping[str, str]
    required: frozenset[ChiFeatureKey] = frozenset()
    role_sets: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        roles = dict(self.roles)
        if any(
            not isinstance(role, str)
            or not role
            or not isinstance(participant, str)
            or not participant
            for role, participant in roles.items()
        ):
            raise ValueError(
                "CHI feature contract roles require non-empty names"
            )
        role_sets = dict(self.role_sets)
        normalized_role_sets: dict[str, frozenset[str]] = {}
        for role, members in role_sets.items():
            if not isinstance(role, str) or not role:
                raise ValueError(
                    "CHI feature contract role-set names must be non-empty"
                )
            if isinstance(members, (str, bytes)):
                raise TypeError(
                    "CHI feature contract role sets require participant "
                    "collections, not strings"
                )
            try:
                member_set = frozenset(members)
            except TypeError as error:
                raise TypeError(
                    "CHI feature contract role sets must be iterable"
                ) from error
            if any(
                not isinstance(member, str) or not member
                for member in member_set
            ):
                raise ValueError(
                    "CHI feature contract role-set members require "
                    "non-empty participant names"
                )
            normalized_role_sets[role] = member_set
        overlap = set(roles) & set(normalized_role_sets)
        if overlap:
            raise ValueError(
                "CHI roles cannot be bound as both scalar and finite set: "
                f"{sorted(overlap)!r}"
            )
        required = frozenset(self.required)
        if any(not isinstance(item, ChiFeatureKey) for item in required):
            raise TypeError(
                "CHI required features require ChiFeatureKey values"
            )
        object.__setattr__(self, "roles", MappingProxyType(roles))
        object.__setattr__(self, "required", required)
        object.__setattr__(
            self,
            "role_sets",
            MappingProxyType(normalized_role_sets),
        )

    def role_members(self, role: str) -> tuple[str, ...] | None:
        """Return a deterministic binding tuple, or ``None`` if unbound."""

        if not isinstance(role, str) or not role:
            raise ValueError("CHI role lookup requires a non-empty name")
        participant = self.roles.get(role)
        if participant is not None:
            return (participant,)
        members = self.role_sets.get(role)
        if members is None:
            return None
        return tuple(sorted(members))

    def role_is_set(self, role: str) -> bool:
        """Whether ``role`` was explicitly declared as a finite set."""

        if not isinstance(role, str) or not role:
            raise ValueError("CHI role lookup requires a non-empty name")
        return role in self.role_sets

    @property
    def participant_names(self) -> frozenset[str]:
        """All participants named by scalar and finite-set bindings."""

        return frozenset(self.roles.values()).union(
            *self.role_sets.values()
        )


@dataclass(frozen=True)
class ChiBoundFlowRequirement:
    """One concrete source/target obligation expanded from a role flow."""

    key: str
    requirement: ChiFlowRequirement
    source: str
    target: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("CHI bound flow requirement needs an evidence key")
        if not isinstance(self.requirement, ChiFlowRequirement):
            raise TypeError(
                "CHI bound flow requirement needs a flow requirement"
            )
        for value, subject in (
            (self.source, "source"),
            (self.target, "target"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"CHI bound flow requirement needs a {subject}"
                )


def bind_chi_flow_requirement(
    contract: ChiFeatureContract,
    requirement: ChiFlowRequirement,
) -> tuple[ChiBoundFlowRequirement, ...] | None:
    """Expand a role-level flow into deterministic endpoint obligations.

    ``None`` means at least one abstract role is unbound.  An empty tuple is a
    valid vacuous result when an explicitly declared finite role set is empty.
    If either endpoint is a role set, the result is the Cartesian product of
    source and target members; this proves every declared target path rather
    than treating one representative as evidence for the whole domain.
    """

    if not isinstance(contract, ChiFeatureContract):
        raise TypeError("CHI flow binding requires a feature contract")
    if not isinstance(requirement, ChiFlowRequirement):
        raise TypeError("CHI flow binding requires a flow requirement")
    sources = contract.role_members(requirement.source_role)
    targets = contract.role_members(requirement.target_role)
    if sources is None or targets is None:
        return None
    expanded = contract.role_is_set(
        requirement.source_role
    ) or contract.role_is_set(requirement.target_role)
    return tuple(
        ChiBoundFlowRequirement(
            (
                f"{_flow_key_atom(requirement.name)}"
                f"[{_flow_key_atom(source)}->{_flow_key_atom(target)}]"
                if expanded
                else requirement.name
            ),
            requirement,
            source,
            target,
        )
        for source, target in product(sources, targets)
    )


def _flow_key_atom(value: str) -> str:
    """Escape delimiters while keeping ordinary participant names readable."""

    return quote(value, safe="._-~")


class ChiCapabilityGapKind(str, Enum):
    DEPENDENCY = "dependency"
    ROLE = "role"
    PARTICIPANT = "participant"
    FLOW = "flow"
    SYSTEM = "system"


@dataclass(frozen=True)
class ChiCapabilityGap:
    """One unsatisfied atomic obligation in a feature closure."""

    feature: ChiFeatureKey
    kind: ChiCapabilityGapKind
    subject: str
    reason: str
    missing: tuple[ChiCapabilityKey, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.feature, ChiFeatureKey):
            raise TypeError("CHI capability gap requires a feature key")
        try:
            kind = ChiCapabilityGapKind(self.kind)
        except (TypeError, ValueError) as error:
            raise ValueError("CHI capability gap has an unknown kind") from error
        if not isinstance(self.subject, str) or not self.subject:
            raise ValueError("CHI capability gap requires a subject")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("CHI capability gap requires a reason")
        missing = tuple(sorted(set(self.missing)))
        if any(not isinstance(item, ChiCapabilityKey) for item in missing):
            raise TypeError(
                "CHI capability gap missing values require capability keys"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "missing", missing)


@dataclass(frozen=True)
class ChiFeatureEvidence:
    """Participant and flow facts that closed one feature."""

    feature: ChiFeatureKey
    participants: Mapping[str, ChiParticipantCapability]
    flows: Mapping[str, ChiFlowCapability]
    dependencies: tuple[ChiFeatureKey, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "participants",
            MappingProxyType(dict(self.participants)),
        )
        object.__setattr__(
            self, "flows", MappingProxyType(dict(self.flows))
        )
        object.__setattr__(
            self, "dependencies", tuple(self.dependencies)
        )


class ChiCapabilityClosureError(ValueError):
    """Raised when a caller requires an unavailable CHI feature."""

    def __init__(
        self,
        feature: ChiFeatureKey | None,
        gaps: tuple[ChiCapabilityGap, ...],
    ) -> None:
        self.feature = feature
        self.gaps = tuple(gaps)
        label = "required CHI features" if feature is None else str(feature)
        details = "; ".join(gap.reason for gap in self.gaps)
        super().__init__(f"{label} capability closure failed: {details}")


@dataclass(frozen=True)
class ResolvedChiCapabilities:
    """Availability report produced from one immutable feature catalog."""

    catalog: ChiFeatureCatalog
    contract: ChiFeatureContract
    evidence_by_feature: Mapping[ChiFeatureKey, ChiFeatureEvidence]
    gaps_by_feature: Mapping[
        ChiFeatureKey, tuple[ChiCapabilityGap, ...]
    ]

    def __post_init__(self) -> None:
        evidence = dict(self.evidence_by_feature)
        gaps = {
            feature: tuple(items)
            for feature, items in self.gaps_by_feature.items()
        }
        catalog_keys = set(self.catalog.definitions)
        if set(evidence) | set(gaps) != catalog_keys:
            raise ValueError(
                "CHI capability report must cover every catalog feature"
            )
        if set(evidence) & set(gaps):
            raise ValueError(
                "CHI feature cannot be both available and unavailable"
            )
        if any(not items for items in gaps.values()):
            raise ValueError(
                "unavailable CHI features require at least one gap"
            )
        object.__setattr__(
            self,
            "evidence_by_feature",
            MappingProxyType(evidence),
        )
        object.__setattr__(
            self,
            "gaps_by_feature",
            MappingProxyType(gaps),
        )

    @property
    def available(self) -> Mapping[ChiFeatureKey, ChiFeatureEvidence]:
        return self.evidence_by_feature

    @property
    def unavailable(
        self,
    ) -> Mapping[ChiFeatureKey, tuple[ChiCapabilityGap, ...]]:
        return self.gaps_by_feature

    def supports(self, feature: ChiFeatureKey) -> bool:
        self._require_known(feature)
        return feature in self.evidence_by_feature

    def gaps(
        self, feature: ChiFeatureKey
    ) -> tuple[ChiCapabilityGap, ...]:
        self._require_known(feature)
        return self.gaps_by_feature.get(feature, ())

    def require(self, feature: ChiFeatureKey) -> ChiFeatureEvidence:
        """Return closure evidence or fail before a feature runtime is built."""

        self._require_known(feature)
        evidence = self.evidence_by_feature.get(feature)
        if evidence is None:
            raise ChiCapabilityClosureError(
                feature, self.gaps_by_feature[feature]
            )
        return evidence

    def require_contract(self) -> "ResolvedChiCapabilities":
        gaps = tuple(
            gap
            for feature in sorted(self.contract.required)
            for gap in self.gaps_by_feature.get(feature, ())
        )
        if gaps:
            raise ChiCapabilityClosureError(None, gaps)
        for feature in self.contract.required:
            self._require_known(feature)
        return self

    def _require_known(self, feature: ChiFeatureKey) -> None:
        if not isinstance(feature, ChiFeatureKey):
            raise TypeError("CHI feature query requires ChiFeatureKey")
        if feature not in self.catalog.definitions:
            raise KeyError(f"unknown CHI feature {feature}")


def resolve_chi_capabilities(
    contract: ChiFeatureContract,
    *,
    participants: tuple[ChiParticipantCapability, ...],
    flows: tuple[ChiFlowCapability, ...],
    system_capabilities: frozenset[ChiCapabilityKey] = frozenset(),
    catalog: ChiFeatureCatalog = CHI_BUILTIN_FEATURE_CATALOG,
) -> ResolvedChiCapabilities:
    """Resolve every catalog feature and retain gaps for unavailable ones."""

    if not isinstance(contract, ChiFeatureContract):
        raise TypeError("CHI capability resolution requires a feature contract")
    if not isinstance(catalog, ChiFeatureCatalog):
        raise TypeError("CHI capability resolution requires a feature catalog")
    participant_items = tuple(participants)
    flow_items = tuple(flows)
    if any(
        not isinstance(item, ChiParticipantCapability)
        for item in participant_items
    ):
        raise TypeError(
            "CHI capability participants require explicit capability claims"
        )
    if any(not isinstance(item, ChiFlowCapability) for item in flow_items):
        raise TypeError(
            "CHI capability flows require ChiFlowCapability values"
        )
    participant_by_name = {
        item.participant: item for item in participant_items
    }
    if len(participant_by_name) != len(participant_items):
        raise ValueError("CHI participant capability names must be unique")
    system_capabilities = frozenset(system_capabilities)
    if any(
        not isinstance(item, ChiCapabilityKey)
        for item in system_capabilities
    ):
        raise TypeError(
            "CHI system capability facts require ChiCapabilityKey values"
        )
    unknown_required = contract.required - set(catalog.definitions)
    if unknown_required:
        raise ValueError(
            "CHI feature contract requires unknown features: "
            f"{sorted(str(item) for item in unknown_required)!r}"
        )

    evidence_by_feature: dict[ChiFeatureKey, ChiFeatureEvidence] = {}
    gaps_by_feature: dict[
        ChiFeatureKey, tuple[ChiCapabilityGap, ...]
    ] = {}
    resolving: set[ChiFeatureKey] = set()

    def resolve(feature: ChiFeatureKey) -> None:
        if feature in evidence_by_feature or feature in gaps_by_feature:
            return
        if feature in resolving:
            raise RuntimeError("validated CHI feature catalog became cyclic")
        resolving.add(feature)
        definition = catalog.definitions[feature]
        gaps: list[ChiCapabilityGap] = []
        participant_evidence: dict[str, ChiParticipantCapability] = {}
        flow_evidence: dict[str, ChiFlowCapability] = {}

        for dependency in sorted(definition.dependencies):
            resolve(dependency)
            if dependency in gaps_by_feature:
                gaps.append(
                    ChiCapabilityGap(
                        feature,
                        ChiCapabilityGapKind.DEPENDENCY,
                        str(dependency),
                        f"dependency {dependency} is unavailable",
                    )
                )

        for requirement in definition.roles:
            participant_names = contract.role_members(requirement.role)
            if participant_names is None:
                gaps.append(
                    ChiCapabilityGap(
                        feature,
                        ChiCapabilityGapKind.ROLE,
                        requirement.role,
                        f"role {requirement.role!r} is not bound",
                    )
                )
                continue
            if (
                requirement.cardinality is ChiRoleCardinality.SINGLE
                and contract.role_is_set(requirement.role)
            ):
                gaps.append(
                    ChiCapabilityGap(
                        feature,
                        ChiCapabilityGapKind.ROLE,
                        requirement.role,
                        f"role {requirement.role!r} requires one participant, "
                        "not a finite-set binding",
                    )
                )
                continue
            if len(participant_names) < requirement.minimum_members:
                gaps.append(
                    ChiCapabilityGap(
                        feature,
                        ChiCapabilityGapKind.ROLE,
                        requirement.role,
                        f"role {requirement.role!r} requires at least "
                        f"{requirement.minimum_members} participant(s), "
                        f"found {len(participant_names)}",
                    )
                )
                continue
            for participant_name in participant_names:
                participant = participant_by_name.get(participant_name)
                if participant is None:
                    gaps.append(
                        ChiCapabilityGap(
                            feature,
                            ChiCapabilityGapKind.PARTICIPANT,
                            participant_name,
                            f"participant {participant_name!r} has no "
                            "capability declaration",
                        )
                    )
                    continue
                missing = participant.missing(requirement.capabilities)
                if missing:
                    names = ", ".join(
                        str(item) for item in sorted(missing)
                    )
                    gaps.append(
                        ChiCapabilityGap(
                            feature,
                            ChiCapabilityGapKind.PARTICIPANT,
                            participant_name,
                            f"participant {participant_name!r} lacks {names}",
                            tuple(missing),
                        )
                    )
                    continue
                evidence_key = (
                    f"{requirement.role}[{participant_name}]"
                    if contract.role_is_set(requirement.role)
                    else requirement.role
                )
                participant_evidence[evidence_key] = participant

        for requirement in definition.flows:
            obligations = bind_chi_flow_requirement(contract, requirement)
            if obligations is None:
                gaps.append(
                    ChiCapabilityGap(
                        feature,
                        ChiCapabilityGapKind.FLOW,
                        requirement.name,
                        f"flow {requirement.name!r} cannot resolve its roles",
                    )
                )
                continue
            for obligation in obligations:
                source = obligation.source
                target = obligation.target
                candidates = tuple(
                    flow
                    for flow in flow_items
                    if flow.source == source
                    and flow.target == target
                    and flow.channel is requirement.channel
                )
                if not candidates:
                    gaps.append(
                        ChiCapabilityGap(
                            feature,
                            ChiCapabilityGapKind.FLOW,
                            obligation.key,
                            f"flow {obligation.key!r} has no "
                            f"{requirement.channel.value.upper()} path "
                            f"{source} -> {target}",
                        )
                    )
                    continue
                satisfied = next(
                    (
                        candidate
                        for candidate in candidates
                        if requirement.capabilities <= candidate.provides
                    ),
                    None,
                )
                if satisfied is None:
                    best = min(
                        candidates,
                        key=lambda candidate: len(
                            requirement.capabilities - candidate.provides
                        ),
                    )
                    missing = requirement.capabilities - best.provides
                    names = ", ".join(
                        str(item) for item in sorted(missing)
                    )
                    gaps.append(
                        ChiCapabilityGap(
                            feature,
                            ChiCapabilityGapKind.FLOW,
                            obligation.key,
                            f"flow {best.name!r} lacks {names}",
                            tuple(missing),
                        )
                    )
                    continue
                flow_evidence[obligation.key] = satisfied

        missing_system = (
            definition.system_capabilities - system_capabilities
        )
        if missing_system:
            names = ", ".join(
                str(item) for item in sorted(missing_system)
            )
            gaps.append(
                ChiCapabilityGap(
                    feature,
                    ChiCapabilityGapKind.SYSTEM,
                    "system",
                    f"system lacks {names}",
                    tuple(missing_system),
                )
            )

        resolving.remove(feature)
        if gaps:
            gaps_by_feature[feature] = tuple(gaps)
        else:
            evidence_by_feature[feature] = ChiFeatureEvidence(
                feature,
                participant_evidence,
                flow_evidence,
                tuple(sorted(definition.dependencies)),
            )

    for feature in catalog.definitions:
        resolve(feature)

    return ResolvedChiCapabilities(
        catalog,
        contract,
        evidence_by_feature,
        gaps_by_feature,
    )


__all__ = [
    "CHI_BASE_PATH_CAPABILITIES",
    "CHI_BUILTIN_FEATURE_CATALOG",
    "CHI_CLEAN_EVICT_DEFINITION",
    "CHI_CLEAN_EVICT_RETRY_DEFINITION",
    "CHI_CLEAN_READ_SHARED_DEFINITION",
    "CHI_CLEAN_READ_UNIQUE_DEFINITION",
    "CHI_CLEAN_READ_UNIQUE_NDERR_DEFINITION",
    "CHI_CLEAN_READ_UNIQUE_RETRY_DEFINITION",
    "CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION",
    "CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION",
    "CHI_DIRTY_UNIQUE_TRANSFER_DEFINITION",
    "CHI_DIRTY_WRITEBACK_DEFINITION",
    "CHI_MAKE_UNIQUE_DEFINITION",
    "CHI_MESI_READ_NOT_SHARED_DIRTY_DEFINITION",
    "CHI_FEATURE_READ_NO_SNP_NDERR",
    "CHI_FEATURE_CLEAN_READ_SHARED",
    "CHI_FEATURE_CLEAN_EVICT",
    "CHI_FEATURE_CLEAN_EVICT_RETRY",
    "CHI_FEATURE_CLEAN_READ_UNIQUE",
    "CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR",
    "CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY",
    "CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS",
    "CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER",
    "CHI_FEATURE_DIRTY_UNIQUE_TRANSFER",
    "CHI_FEATURE_DIRTY_WRITEBACK",
    "CHI_FEATURE_MAKE_UNIQUE",
    "CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY",
    "CHI_MESI_NO_SD_REQUIRED_FEATURES",
    "CHI_FEATURE_READ_NO_SNP",
    "CHI_FEATURE_REQUEST_RETRY",
    "CHI_PATH_ROUTING_IDENTITY_PRESERVED",
    "CHI_PATH_TYPED_PROTOCOL",
    "CHI_READ_NO_SNP_DEFINITION",
    "CHI_READ_NO_SNP_NDERR_DEFINITION",
    "CHI_REQUEST_RETRY_DEFINITION",
    "CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_READ_UNIQUE_NDERR_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE",
    "CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE",
    "CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE",
    "CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE",
    "CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE",
    "CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE",
    "ChiBoundFlowRequirement",
    "ChiCapabilityClosureError",
    "ChiCapabilityGap",
    "ChiCapabilityGapKind",
    "ChiFeatureCatalog",
    "ChiFeatureContract",
    "ChiFeatureDefinition",
    "ChiFeatureEvidence",
    "ChiFeatureKey",
    "ChiFlowCapability",
    "ChiFlowRequirement",
    "ChiRoleCardinality",
    "ChiRoleRequirement",
    "ResolvedChiCapabilities",
    "bind_chi_flow_requirement",
    "resolve_chi_capabilities",
]
