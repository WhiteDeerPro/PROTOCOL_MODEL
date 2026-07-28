"""One construction-time closure joining CHI system authority and flows.

Generic SystemProtocol elaboration proves weak module/port/connection
structure.  This CHI-family construction adds the facts required before a CHI
transaction runtime can be trusted:

* transaction and forwarding facets are bound to canonical VirtualDuts;
* NodeID ownership is unambiguous;
* one explicit address-claim scope selects its Home and coherence domain;
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
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_MAKE_UNIQUE,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    ChiCapabilityKey,
    ChiFeatureCatalog,
    ChiFeatureContract,
    ChiFeatureKey,
    ResolvedChiCapabilities,
    resolve_chi_capabilities,
)
from .capability_projection import (
    ChiFlowProjection,
    project_chi_flow_capabilities,
)
from .authority import (
    ChiCoherenceAuthorityContract,
    ChiResolvedCoherenceAuthorityPlan,
    ChiResolvedHomeAuthority,
    resolve_chi_coherence_authority,
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
    authority_plan: ChiResolvedCoherenceAuthorityPlan
    feature_address_claim: str
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
        if not isinstance(
            self.authority_plan, ChiResolvedCoherenceAuthorityPlan
        ):
            raise TypeError(
                "resolved CHI system requires a coherence authority plan"
            )
        if self.authority_plan.system is not self.system:
            raise ValueError(
                "resolved CHI authority must describe the same system"
            )
        if (
            not isinstance(self.feature_address_claim, str)
            or not self.feature_address_claim
        ):
            raise ValueError(
                "resolved CHI system requires a feature address claim"
            )
        authority = self.authority_plan.authority_for_claim(
            self.feature_address_claim
        )
        if self.feature_contract.role_members("home") != (authority.home,):
            raise ValueError(
                "resolved CHI Home role must come from its address authority"
            )
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
    def feature_authority(self) -> ChiResolvedHomeAuthority:
        """Return the Home/domain authority selected for this feature scope."""

        return self.authority_plan.authority_for_claim(
            self.feature_address_claim
        )

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
        """Require authority, identity, and features before opening a session."""

        self.authority_plan.authority_for_claim(
            self.feature_address_claim
        )
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
    authority_contract: ChiCoherenceAuthorityContract,
    feature_address_claim: str,
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
    if not isinstance(
        authority_contract, ChiCoherenceAuthorityContract
    ):
        raise TypeError(
            "CHI system resolution requires a coherence authority contract"
        )
    if (
        not isinstance(feature_address_claim, str)
        or not feature_address_claim
    ):
        raise ValueError(
            "CHI system resolution requires a feature address claim"
        )
    if not isinstance(catalog, ChiFeatureCatalog):
        raise TypeError("CHI system resolution requires a feature catalog")
    feature_closure: set[ChiFeatureKey] = set()

    def add_feature(feature: ChiFeatureKey) -> None:
        if feature in feature_closure:
            return
        definition = catalog.definitions.get(feature)
        if definition is None:
            return
        feature_closure.add(feature)
        for dependency in definition.dependencies:
            add_feature(dependency)

    for required in feature_contract.required:
        add_feature(required)
    if (
        CHI_FEATURE_CLEAN_READ_SHARED in feature_closure
        and {
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
            CHI_FEATURE_MAKE_UNIQUE,
            CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
        }
        & feature_closure
    ):
        raise ValueError(
            "the current CHI coherence runtime cannot combine ReadShared "
            "with a dirty-owner feature; select the MESI "
            "ReadNotSharedDirty policy preset instead"
        )
    if (
        {
            CHI_FEATURE_MAKE_UNIQUE,
            CHI_FEATURE_CLEAN_READ_UNIQUE,
        }
        <= feature_closure
        and CHI_FEATURE_DIRTY_UNIQUE_TRANSFER
        not in feature_closure
    ):
        raise ValueError(
            "the current staged CHI system profile combines MakeUnique and "
            "ReadUnique only with dirty Unique transfer enabled"
        )
    if (
        {
            CHI_FEATURE_MAKE_UNIQUE,
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
        }
        <= feature_closure
        and CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
        not in feature_closure
    ):
        raise ValueError(
            "the current staged CHI system profile combines MakeUnique and "
            "CleanUnique only with shared-dirty peer handling enabled"
        )
    if (
        {
            CHI_FEATURE_MAKE_UNIQUE,
            CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
        }
        <= feature_closure
    ):
        raise ValueError(
            "the current staged CHI system profile does not combine "
            "MakeUnique with MESI ReadNotSharedDirty until both same-line "
            "transient Snoop directions are implemented"
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

    identities = resolve_chi_node_identities(system, facet_items)
    authority_plan = resolve_chi_coherence_authority(
        system,
        facet_items,
        identities,
        authority_contract,
    )
    effective_contract = _bind_feature_authority(
        feature_contract,
        authority_plan,
        feature_address_claim,
        catalog,
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
    projection = project_chi_flow_capabilities(
        network,
        effective_contract,
        bindings=tuple(bindings.values()),
        catalog=catalog,
        target_node_id_by_participant=target_node_id_by_participant,
    )
    capabilities = resolve_chi_capabilities(
        effective_contract,
        participants=tuple(participant_capabilities),
        flows=projection.flows,
        system_capabilities=system_capabilities,
        catalog=catalog,
    )
    return ResolvedChiSystem(
        system,
        facet_items,
        effective_contract,
        identities,
        authority_plan,
        feature_address_claim,
        projection,
        capabilities,
        network,
        bindings,
        forwarding,
    )


def _bind_feature_authority(
    feature_contract: ChiFeatureContract,
    authority_plan: ChiResolvedCoherenceAuthorityPlan,
    feature_address_claim: str,
    catalog: ChiFeatureCatalog,
) -> ChiFeatureContract:
    """Derive Home and eligible Snoopee roles from one address scope.

    The caller still chooses the initiating Requester and required features.
    Home and Snoopee are system authority, so accepting them as parallel
    caller-authored role facts would recreate the construction inversion this
    resolver is intended to remove.
    """

    derived_roles = {"home", "snoopee"}
    duplicated = derived_roles & (
        set(feature_contract.roles) | set(feature_contract.role_sets)
    )
    if duplicated:
        raise ValueError(
            "CHI system feature intent must not bind authority-derived roles: "
            f"{sorted(duplicated)!r}"
        )
    unknown_required = (
        feature_contract.required - set(catalog.definitions)
    )
    if unknown_required:
        raise ValueError(
            "CHI feature contract requires unknown features: "
            f"{sorted(str(item) for item in unknown_required)!r}"
        )

    required_roles: set[str] = set()
    requires_coherence_domain = False
    visited: set[ChiFeatureKey] = set()

    def visit(feature: ChiFeatureKey) -> None:
        nonlocal requires_coherence_domain
        if feature in visited:
            return
        visited.add(feature)
        definition = catalog.definitions[feature]
        required_roles.update(item.role for item in definition.roles)
        requires_coherence_domain = (
            requires_coherence_domain
            or definition.requires_coherence_domain
        )
        for dependency in definition.dependencies:
            visit(dependency)

    for feature in feature_contract.required:
        visit(feature)

    authority = authority_plan.authority_for_claim(
        feature_address_claim
    )
    roles = dict(feature_contract.roles)
    role_sets = dict(feature_contract.role_sets)
    roles["home"] = authority.home

    eligible_snoopees: tuple[str, ...] | None = None
    if requires_coherence_domain or "snoopee" in required_roles:
        requester_members = feature_contract.role_members("requester")
        if (
            requester_members is None
            or len(requester_members) != 1
            or feature_contract.role_is_set("requester")
        ):
            raise ValueError(
                "coherence authority derivation requires one scalar requester"
            )
        if authority.coherence_domain is None:
            raise ValueError(
                f"CHI Home authority for claim {feature_address_claim!r} "
                "does not select a coherence domain"
            )
        eligible_snoopees = authority_plan.eligible_snoopees(
            feature_address_claim,
            requester_members[0],
        )
    if "snoopee" in required_roles:
        assert eligible_snoopees is not None
        role_sets["snoopee"] = frozenset(eligible_snoopees)

    return ChiFeatureContract(
        roles,
        feature_contract.required,
        role_sets,
    )


__all__ = ["ResolvedChiSystem", "resolve_chi_system"]
