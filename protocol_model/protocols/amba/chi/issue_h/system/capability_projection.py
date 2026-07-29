"""Project executable CHI network paths into capability-flow evidence.

The generic topology records directed connections, but a connection is not
automatically an executable CHI path.  This projector deliberately consumes a
constructed :class:`ChiTransportNetworkSession`: every hop has therefore
passed its CHI profile and shared-Link runtime checks.  It additionally
closes endpoint channel declarations, target-NodeID router decisions, NodeID
field widths, per-hop DAT-width facts, and end-to-end reachability before
emitting ``ChiFlowCapability``.

Participant behavior remains an explicit offer supplied separately to
``resolve_chi_capabilities``.  Network structure cannot prove that an RN
stores P-Credits or that a Home implements Retry policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.system.topology.model import VirtualDutPortRef
from protocol_model.virtual_dut.boundary.transport import TransportDirection

from ..participants import (
    ChiParticipantBinding,
    ChiParticipantCapability,
)
from ..representation import ChiChannelKind
from .capability import (
    CHI_BASE_PATH_CAPABILITIES,
    CHI_BUILTIN_FEATURE_CATALOG,
    CHI_PATH_DAT_512,
    ChiCapabilityKey,
    ChiFeatureCatalog,
    ChiFeatureContract,
    ChiFlowCapability,
    ResolvedChiCapabilities,
    bind_chi_flow_requirement,
    resolve_chi_capabilities,
)
from .network import ChiTransportNetworkSession


class ChiFlowProjectionGapKind(str, Enum):
    ROLE = "role"
    PARTICIPANT = "participant"
    NODE_ID = "node_id"
    PORT = "port"
    TOPOLOGY = "topology"
    CHANNEL = "channel"
    ROUTE = "route"
    CYCLE = "cycle"


@dataclass(frozen=True)
class ChiFlowProjectionGap:
    """Why one catalog flow could not become executable path evidence."""

    requirement: str
    source_role: str
    target_role: str
    channel: ChiChannelKind
    kind: ChiFlowProjectionGapKind
    reason: str

    def __post_init__(self) -> None:
        for value, subject in (
            (self.requirement, "requirement"),
            (self.source_role, "source role"),
            (self.target_role, "target role"),
            (self.reason, "reason"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"CHI flow projection gap requires a {subject}"
                )
        try:
            channel = ChiChannelKind(self.channel)
            kind = ChiFlowProjectionGapKind(self.kind)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI flow projection gap has an unknown channel or kind"
            ) from error
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True)
class ChiFlowProjection:
    """Runnable flows and diagnostics derived from one network session."""

    flows: tuple[ChiFlowCapability, ...]
    gaps: tuple[ChiFlowProjectionGap, ...]
    flow_by_requirement: Mapping[str, ChiFlowCapability]

    def __post_init__(self) -> None:
        flows = tuple(self.flows)
        gaps = tuple(self.gaps)
        by_requirement = dict(self.flow_by_requirement)
        if any(not isinstance(item, ChiFlowCapability) for item in flows):
            raise TypeError(
                "CHI flow projection contains non-flow evidence"
            )
        if any(not isinstance(item, ChiFlowProjectionGap) for item in gaps):
            raise TypeError("CHI flow projection contains invalid gaps")
        if any(item not in flows for item in by_requirement.values()):
            raise ValueError(
                "CHI flow requirement evidence must reference projected flows"
            )
        object.__setattr__(self, "flows", flows)
        object.__setattr__(self, "gaps", gaps)
        object.__setattr__(
            self,
            "flow_by_requirement",
            MappingProxyType(by_requirement),
        )


@dataclass(frozen=True)
class _TraceFailure:
    kind: ChiFlowProjectionGapKind
    reason: str


def project_chi_flow_capabilities(
    network: ChiTransportNetworkSession,
    contract: ChiFeatureContract,
    *,
    bindings: tuple[ChiParticipantBinding, ...],
    catalog: ChiFeatureCatalog = CHI_BUILTIN_FEATURE_CATALOG,
    target_node_id_by_participant: Mapping[str, int] | None = None,
) -> ChiFlowProjection:
    """Derive catalog flow evidence from executable hops and router routes.

    When a target binding owns more than one NodeID, callers must select the
    identity relevant to this construction.  This avoids claiming that one
    successful route proves reachability for every identity owned by a
    compound participant.
    """

    if not isinstance(network, ChiTransportNetworkSession):
        raise TypeError(
            "CHI flow projection requires ChiTransportNetworkSession; "
            "generic topology alone is not executable-path evidence"
        )
    if not isinstance(contract, ChiFeatureContract):
        raise TypeError("CHI flow projection requires ChiFeatureContract")
    if not isinstance(catalog, ChiFeatureCatalog):
        raise TypeError("CHI flow projection requires ChiFeatureCatalog")
    binding_items = tuple(bindings)
    if any(not isinstance(item, ChiParticipantBinding) for item in binding_items):
        raise TypeError(
            "CHI flow projection bindings require ChiParticipantBinding"
        )
    binding_by_name = {item.name: item for item in binding_items}
    if len(binding_by_name) != len(binding_items):
        raise ValueError("CHI flow projection binding names must be unique")
    for binding in binding_items:
        system_dut = network.system.spec.virtual_duts.get(binding.dut.name)
        if system_dut is None or system_dut != binding.dut:
            raise ValueError(
                f"CHI participant {binding.name!r} is not bound to this "
                "network system"
            )
    target_selection = dict(target_node_id_by_participant or {})
    unknown_selection = set(target_selection) - set(binding_by_name)
    if unknown_selection:
        raise ValueError(
            "CHI target NodeID selection references unknown participants: "
            f"{sorted(unknown_selection)!r}"
        )

    requirements = _contract_flow_requirements(catalog, contract)
    projected: list[ChiFlowCapability] = []
    gaps: list[ChiFlowProjectionGap] = []
    by_requirement: dict[str, ChiFlowCapability] = {}
    flow_by_key: dict[
        tuple[str, str, ChiChannelKind, tuple[str, ...]],
        ChiFlowCapability,
    ] = {}

    for feature, requirement in requirements:
        obligations = bind_chi_flow_requirement(contract, requirement)
        if obligations is None:
            requirement_name = f"{feature.name}:{requirement.name}"
            gaps.append(
                ChiFlowProjectionGap(
                    requirement_name,
                    requirement.source_role,
                    requirement.target_role,
                    requirement.channel,
                    ChiFlowProjectionGapKind.ROLE,
                    f"flow {requirement.name!r} cannot resolve its roles",
                )
            )
            continue
        for obligation in obligations:
            requirement_name = f"{feature.name}:{obligation.key}"
            source_name = obligation.source
            target_name = obligation.target
            source = binding_by_name.get(source_name)
            target = binding_by_name.get(target_name)
            if source is None or target is None:
                missing = source_name if source is None else target_name
                gaps.append(
                    ChiFlowProjectionGap(
                        requirement_name,
                        requirement.source_role,
                        requirement.target_role,
                        requirement.channel,
                        ChiFlowProjectionGapKind.PARTICIPANT,
                        f"participant {missing!r} has no CHI binding",
                    )
                )
                continue
            target_id, target_failure = _select_target_id(
                target,
                target_selection.get(target.name),
            )
            if target_failure is not None:
                gaps.append(
                    ChiFlowProjectionGap(
                        requirement_name,
                        requirement.source_role,
                        requirement.target_role,
                        requirement.channel,
                        target_failure.kind,
                        target_failure.reason,
                    )
                )
                continue
            assert target_id is not None
            connections, failure = _trace_participant_path(
                network,
                source,
                target,
                requirement.channel,
                target_id,
            )
            if failure is not None:
                gaps.append(
                    ChiFlowProjectionGap(
                        requirement_name,
                        requirement.source_role,
                        requirement.target_role,
                        requirement.channel,
                        failure.kind,
                        failure.reason,
                    )
                )
                continue
            assert connections is not None
            key = (
                source.name,
                target.name,
                requirement.channel,
                connections,
            )
            flow = flow_by_key.get(key)
            if flow is None:
                flow = ChiFlowCapability(
                    f"projected.{source.name}.{target.name}."
                    f"{requirement.channel.value}",
                    source.name,
                    target.name,
                    requirement.channel,
                    provides=_path_capabilities(
                        network,
                        requirement.channel,
                        connections,
                    ),
                    connections=connections,
                )
                flow_by_key[key] = flow
                projected.append(flow)
            by_requirement[requirement_name] = flow

    return ChiFlowProjection(
        tuple(projected),
        tuple(gaps),
        by_requirement,
    )


def resolve_projected_chi_capabilities(
    network: ChiTransportNetworkSession,
    contract: ChiFeatureContract,
    *,
    bindings: tuple[ChiParticipantBinding, ...],
    participant_capabilities: tuple[ChiParticipantCapability, ...],
    system_capabilities: frozenset[ChiCapabilityKey] = frozenset(),
    catalog: ChiFeatureCatalog = CHI_BUILTIN_FEATURE_CATALOG,
    target_node_id_by_participant: Mapping[str, int] | None = None,
) -> ResolvedChiCapabilities:
    """Project runnable flows, then close explicitly offered behavior."""

    projection = project_chi_flow_capabilities(
        network,
        contract,
        bindings=bindings,
        catalog=catalog,
        target_node_id_by_participant=target_node_id_by_participant,
    )
    return resolve_chi_capabilities(
        contract,
        participants=participant_capabilities,
        flows=projection.flows,
        system_capabilities=system_capabilities,
        catalog=catalog,
    )


def _contract_flow_requirements(
    catalog: ChiFeatureCatalog,
    contract: ChiFeatureContract,
):
    """Return flows needed by the contract and its feature dependencies."""

    unknown = contract.required - set(catalog.definitions)
    if unknown:
        raise ValueError(
            "CHI feature contract requires unknown features: "
            f"{sorted(str(item) for item in unknown)!r}"
        )
    selected = set()

    def include(feature) -> None:
        if feature in selected:
            return
        selected.add(feature)
        for dependency in catalog.definitions[feature].dependencies:
            include(dependency)

    for feature in contract.required:
        include(feature)
    return tuple(
        (feature, requirement)
        for feature, definition in catalog.definitions.items()
        if feature in selected
        for requirement in definition.flows
    )


def _select_target_id(
    binding: ChiParticipantBinding,
    selected: int | None,
) -> tuple[int | None, _TraceFailure | None]:
    node_ids = binding.node_ids
    if selected is not None:
        if (
            not isinstance(selected, int)
            or isinstance(selected, bool)
            or selected < 0
        ):
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.NODE_ID,
                f"selected NodeID for {binding.name!r} is invalid",
            )
        if selected not in node_ids:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.NODE_ID,
                f"selected NodeID {selected} is not offered by "
                f"{binding.name!r}",
            )
        return selected, None
    if len(node_ids) != 1:
        return None, _TraceFailure(
            ChiFlowProjectionGapKind.NODE_ID,
            f"participant {binding.name!r} requires one selected target "
            f"NodeID, found {len(node_ids)}",
        )
    return next(iter(node_ids)), None


def _trace_participant_path(
    network: ChiTransportNetworkSession,
    source: ChiParticipantBinding,
    target: ChiParticipantBinding,
    channel: ChiChannelKind,
    target_id: int,
) -> tuple[tuple[str, ...] | None, _TraceFailure | None]:
    if not source.node_ids:
        return None, _TraceFailure(
            ChiFlowProjectionGapKind.NODE_ID,
            f"source participant {source.name!r} offers no NodeID",
        )
    source_ports = source.ports_for(channel, TransportDirection.TRANSMIT)
    target_ports = target.ports_for(channel, TransportDirection.RECEIVE)
    if not source_ports:
        return None, _TraceFailure(
            ChiFlowProjectionGapKind.PORT,
            f"participant {source.name!r} has no transmit "
            f"{channel.value.upper()} port",
        )
    if not target_ports:
        return None, _TraceFailure(
            ChiFlowProjectionGapKind.PORT,
            f"participant {target.name!r} has no receive "
            f"{channel.value.upper()} port",
        )
    destinations = frozenset(
        VirtualDutPortRef(target.dut.name, port.name)
        for port in target_ports
    )
    successes: set[tuple[str, ...]] = set()
    failures: list[_TraceFailure] = []
    for port in source_ports:
        connections, failure = _trace_from_port(
            network,
            VirtualDutPortRef(source.dut.name, port.name),
            destinations,
            channel,
            source.node_ids | frozenset((target_id,)),
            target_id,
        )
        if connections is not None:
            successes.add(connections)
        elif failure is not None:
            failures.append(failure)
    if len(successes) == 1:
        return next(iter(successes)), None
    if len(successes) > 1:
        return None, _TraceFailure(
            ChiFlowProjectionGapKind.ROUTE,
            f"participant {source.name!r} has multiple runnable "
            f"{channel.value.upper()} paths to {target.name!r}",
        )
    if failures:
        return None, failures[0]
    return None, _TraceFailure(
        ChiFlowProjectionGapKind.TOPOLOGY,
        f"no runnable {channel.value.upper()} path exists from "
        f"{source.name!r} to {target.name!r}",
    )


def _trace_from_port(
    network: ChiTransportNetworkSession,
    source: VirtualDutPortRef,
    destinations: frozenset[VirtualDutPortRef],
    channel: ChiChannelKind,
    participant_node_ids: frozenset[int],
    target_id: int,
) -> tuple[tuple[str, ...] | None, _TraceFailure | None]:
    plan = network.system.transport_plan
    assert plan is not None
    current = source
    visited: set[VirtualDutPortRef] = set()
    connections: list[str] = []
    while True:
        if current in visited:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.CYCLE,
                f"{channel.value.upper()} route cycles at "
                f"{current.qualified_name}",
            )
        visited.add(current)
        outgoing = plan.outgoing_by_port.get(current, ())
        if len(outgoing) != 1:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.TOPOLOGY,
                f"{current.qualified_name!r} has {len(outgoing)} outgoing "
                "transport connections; one is required",
            )
        hop = outgoing[0]
        path = network.paths.get(hop.name)
        if path is None:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.TOPOLOGY,
                f"topology connection {hop.name!r} has no executable "
                "CHI path runtime",
            )
        if channel not in path.channels:
            labels = "/".join(
                item.value.upper()
                for item in sorted(
                    path.channels, key=lambda item: item.value
                )
            )
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.CHANNEL,
                f"topology connection {hop.name!r} exists but its runtime "
                f"carries {labels}, not {channel.value.upper()}",
            )
        node_width = _path_node_id_width(channel, path.link.profile)
        too_wide = tuple(
            node_id
            for node_id in participant_node_ids
            if node_id >= (1 << node_width)
        )
        if too_wide:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.NODE_ID,
                f"connection {hop.name!r} cannot represent participant "
                f"NodeIDs {sorted(too_wide)!r} in {node_width} bits",
            )
        connections.append(hop.name)
        if hop.receiver in destinations:
            return tuple(connections), None
        router = network.routers.get(hop.receiver.dut)
        if router is None:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.ROUTE,
                f"connection {hop.name!r} terminates at "
                f"{hop.receiver.qualified_name!r} before the target "
                "participant",
            )
        matches = tuple(
            route
            for route in router.routes
            if route.target_id == target_id and channel in route.channels
        )
        if len(matches) != 1:
            return None, _TraceFailure(
                ChiFlowProjectionGapKind.ROUTE,
                f"router {router.name!r} resolves {len(matches)} "
                f"{channel.value.upper()} routes for NodeID {target_id}",
            )
        current = VirtualDutPortRef(
            hop.receiver.dut,
            matches[0].egress_port,
        )


def _path_node_id_width(channel, profile) -> int:
    if channel is ChiChannelKind.REQ:
        assert profile.request is not None
        return profile.request.representation.node_id_width
    if channel is ChiChannelKind.RSP:
        assert profile.response is not None
        return profile.response.representation.node_id_width
    if channel is ChiChannelKind.DAT:
        assert profile.data is not None
        return profile.data.representation.node_id_width
    assert channel is ChiChannelKind.SNP
    assert profile.snoop is not None
    return profile.snoop.representation.node_id_width


def _path_capabilities(
    network: ChiTransportNetworkSession,
    channel: ChiChannelKind,
    connections: tuple[str, ...],
) -> frozenset[ChiCapabilityKey]:
    """Derive representation facts shared by every hop in one path."""

    capabilities = set(CHI_BASE_PATH_CAPABILITIES)
    if channel is ChiChannelKind.DAT and connections:
        for name in connections:
            data_profile = network.paths[name].link.profile.data
            if (
                data_profile is None
                or data_profile.representation.data_width != 512
            ):
                break
        else:
            capabilities.add(CHI_PATH_DAT_512)
    return frozenset(capabilities)


__all__ = [
    "ChiFlowProjection",
    "ChiFlowProjectionGap",
    "ChiFlowProjectionGapKind",
    "project_chi_flow_capabilities",
    "resolve_projected_chi_capabilities",
]
