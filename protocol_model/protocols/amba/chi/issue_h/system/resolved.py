"""One construction-time closure joining CHI facets, identity, and flows.

Generic SystemProtocol elaboration proves weak module/port/connection
structure.  This CHI-family construction adds the facts required before a CHI
transaction runtime can be trusted:

* transaction and forwarding facets are bound to canonical VirtualDuts;
* NodeID ownership is unambiguous;
* every required feature has participant behavior offers;
* every required channel flow is executable through the constructed router
  and transport runtime.

The result contains no dynamic transaction state.  It is reusable evidence
from which ReadNoSnp, Retry, and later CHI feature sessions can be opened.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.system.elaboration import ElaboratedSystemProtocol

from ..participants import (
    ChiBehaviorFacet,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiStoreForwardRouterNode,
)
from .capability import (
    CHI_BUILTIN_FEATURE_CATALOG,
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    ChiCapabilityKey,
    ChiFeatureCatalog,
    ChiFeatureContract,
    ResolvedChiCapabilities,
    resolve_chi_capabilities,
)
from .capability_projection import (
    ChiFlowProjection,
    project_chi_flow_capabilities,
)
from .identity import (
    ChiResolvedIdentityPlan,
    resolve_chi_node_identities,
)
from .network import ChiTransportNetworkSession


@dataclass(frozen=True)
class ResolvedChiSystem:
    """Immutable CHI construction evidence plus its stateless network runtime."""

    system: ElaboratedSystemProtocol
    facets: tuple[ChiBehaviorFacet, ...]
    feature_contract: ChiFeatureContract
    identities: ChiResolvedIdentityPlan
    flow_projection: ChiFlowProjection
    capabilities: ResolvedChiCapabilities
    network: ChiTransportNetworkSession
    binding_by_name: Mapping[str, ChiParticipantBinding]
    forwarding_bindings: tuple[ChiParticipantBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.system, ElaboratedSystemProtocol):
            raise TypeError("resolved CHI system requires elaborated topology")
        facets = tuple(self.facets)
        if any(not isinstance(item, ChiBehaviorFacet) for item in facets):
            raise TypeError("resolved CHI system requires behavior facets")
        if not isinstance(self.feature_contract, ChiFeatureContract):
            raise TypeError("resolved CHI system requires a feature contract")
        if not isinstance(self.identities, ChiResolvedIdentityPlan):
            raise TypeError("resolved CHI system requires an identity plan")
        if not isinstance(self.flow_projection, ChiFlowProjection):
            raise TypeError("resolved CHI system requires a flow projection")
        if not isinstance(self.capabilities, ResolvedChiCapabilities):
            raise TypeError("resolved CHI system requires capability evidence")
        if (
            not isinstance(self.network, ChiTransportNetworkSession)
            or self.network.system is not self.system
        ):
            raise ValueError(
                "resolved CHI network must execute the same elaborated system"
            )
        bindings = dict(self.binding_by_name)
        if set(bindings) != {item.name for item in facets}:
            raise ValueError(
                "resolved CHI binding registry must cover every facet"
            )
        if any(
            not isinstance(item, ChiParticipantBinding)
            for item in bindings.values()
        ):
            raise TypeError(
                "resolved CHI binding registry requires participant bindings"
            )
        forwarding = tuple(self.forwarding_bindings)
        if any(
            not isinstance(item, ChiParticipantBinding)
            for item in forwarding
        ):
            raise TypeError(
                "resolved CHI forwarding bindings require participant bindings"
            )
        object.__setattr__(self, "facets", facets)
        object.__setattr__(
            self, "binding_by_name", MappingProxyType(bindings)
        )
        object.__setattr__(self, "forwarding_bindings", forwarding)

    @property
    def is_closed(self) -> bool:
        return (
            self.identities.is_closed
            and all(
                self.capabilities.supports(feature)
                for feature in self.feature_contract.required
            )
        )

    def require_closed(self) -> "ResolvedChiSystem":
        """Require identity and the feature contract before opening a session."""

        self.identities.require_closed()
        self.capabilities.require_contract()
        return self

    def role_binding(self, role: str) -> ChiParticipantBinding:
        """Resolve one feature role to its transaction participant binding."""

        bindings = self.role_bindings(role)
        if len(bindings) != 1:
            raise ValueError(
                f"CHI role {role!r} resolves to {len(bindings)} "
                "participants; use role_bindings() for a finite-set role"
            )
        return bindings[0]

    def role_bindings(self, role: str) -> tuple[ChiParticipantBinding, ...]:
        """Resolve every member of a scalar or finite-set feature role."""

        if not isinstance(role, str) or not role:
            raise ValueError("CHI role lookup requires a non-empty name")
        participants = self.feature_contract.role_members(role)
        if participants is None:
            raise KeyError(f"CHI feature role {role!r} is not bound")
        resolved: list[ChiParticipantBinding] = []
        facet_by_name = {item.name: item for item in self.facets}
        for participant in participants:
            try:
                binding = self.binding_by_name[participant]
            except KeyError as error:
                raise KeyError(
                    f"CHI role {role!r} references unknown participant "
                    f"{participant!r}"
                ) from error
            if facet_by_name[participant].kind is not ChiFacetKind.TRANSACTION:
                raise ValueError(
                    f"CHI role {role!r} resolves to a forwarding facet"
                )
            resolved.append(binding)
        return tuple(resolved)


def resolve_chi_system(
    system: ElaboratedSystemProtocol,
    *,
    facets: tuple[ChiBehaviorFacet, ...],
    feature_contract: ChiFeatureContract,
    participant_capabilities: tuple[ChiParticipantCapability, ...],
    transmitter_capacity_by_connection: Mapping[str, int] | None = None,
    system_capabilities: frozenset[ChiCapabilityKey] = frozenset(),
    catalog: ChiFeatureCatalog = CHI_BUILTIN_FEATURE_CATALOG,
    target_node_id_by_participant: Mapping[str, int] | None = None,
) -> ResolvedChiSystem:
    """Construct and close the current CHI family view of one topology."""

    if not isinstance(system, ElaboratedSystemProtocol):
        raise TypeError("CHI system resolution requires elaborated topology")
    if not isinstance(feature_contract, ChiFeatureContract):
        raise TypeError(
            "CHI system resolution requires a feature contract"
        )
    if (
        CHI_FEATURE_CLEAN_READ_SHARED in feature_contract.required
        and {
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
            CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
        }
        & feature_contract.required
    ):
        raise ValueError(
            "the current CHI coherence runtime cannot combine ReadShared "
            "with a dirty-owner feature; select the MESI "
            "ReadNotSharedDirty policy preset instead"
        )
    facet_items = tuple(facets)
    if any(not isinstance(item, ChiBehaviorFacet) for item in facet_items):
        raise TypeError("CHI system resolution requires behavior facets")
    bindings = {item.name: item.binding for item in facet_items}
    if len(bindings) != len(facet_items):
        raise ValueError(
            "CHI system resolution requires globally unique facet names"
        )
    transaction_names = {
        item.name
        for item in facet_items
        if item.kind is ChiFacetKind.TRANSACTION
    }
    invalid_roles = {
        role: tuple(
            participant
            for participant in (feature_contract.role_members(role) or ())
            if participant not in transaction_names
        )
        for role in (
            tuple(feature_contract.roles)
            + tuple(feature_contract.role_sets)
        )
    }
    invalid_roles = {
        role: participants
        for role, participants in invalid_roles.items()
        if participants
    }
    if invalid_roles:
        raise ValueError(
            "CHI feature roles must reference transaction facets: "
            f"{invalid_roles!r}"
        )

    forwarding = tuple(
        item.binding
        for item in facet_items
        if item.kind is ChiFacetKind.FORWARDING
    )
    routers: dict[str, ChiStoreForwardRouterNode] = {}
    for binding in forwarding:
        if not isinstance(binding.component, ChiStoreForwardRouterNode):
            continue
        if binding.dut.name in routers:
            raise ValueError(
                f"VirtualDut {binding.dut.name!r} has two CHI router facets"
            )
        routers[binding.dut.name] = binding.component

    network = ChiTransportNetworkSession(
        system,
        routers=routers,
        transmitter_capacity_by_connection=(
            transmitter_capacity_by_connection
        ),
    )
    identities = resolve_chi_node_identities(system, facet_items)
    projection = project_chi_flow_capabilities(
        network,
        feature_contract,
        bindings=tuple(bindings.values()),
        catalog=catalog,
        target_node_id_by_participant=target_node_id_by_participant,
    )
    capabilities = resolve_chi_capabilities(
        feature_contract,
        participants=tuple(participant_capabilities),
        flows=projection.flows,
        system_capabilities=system_capabilities,
        catalog=catalog,
    )
    return ResolvedChiSystem(
        system,
        facet_items,
        feature_contract,
        identities,
        projection,
        capabilities,
        network,
        bindings,
        forwarding,
    )


__all__ = ["ResolvedChiSystem", "resolve_chi_system"]
