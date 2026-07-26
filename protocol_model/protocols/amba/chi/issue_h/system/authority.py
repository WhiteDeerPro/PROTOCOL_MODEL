"""CHI Home authority and coherence-domain closure.

The generic system address contract owns receiver address windows.  This
family-local resolver adds CHI meaning by joining one existing address claim
to a Home transaction facet and, optionally, to a finite coherence domain.
It does not copy address ranges or infer membership from topology.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.system.contracts import AddressClaim, AddressWindow
from protocol_model.system.elaboration import ElaboratedSystemProtocol

from ..participants.facet import ChiBehaviorFacet, ChiFacetKind
from .identity import (
    ChiResolvedIdentityPlan,
    ChiResolvedNodeIdentity,
)


@dataclass(frozen=True)
class ChiHomeAuthority:
    """Assign one existing address claim to a CHI Home and domain."""

    address_claim: str
    home: str
    coherence_domain: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.address_claim, str) or not self.address_claim:
            raise ValueError(
                "CHI Home authority requires an address claim name"
            )
        if not isinstance(self.home, str) or not self.home:
            raise ValueError("CHI Home authority requires a Home facet name")
        if self.coherence_domain is not None and (
            not isinstance(self.coherence_domain, str)
            or not self.coherence_domain
        ):
            raise ValueError(
                "CHI Home authority coherence domain must be non-empty or None"
            )


@dataclass(frozen=True)
class ChiCoherenceDomain:
    """Finite coherent-RN membership from which peer Snoopees are derived."""

    name: str
    members: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("CHI coherence domain requires a name")
        try:
            members = frozenset(self.members)
        except TypeError as error:
            raise TypeError(
                "CHI coherence domain members must be iterable"
            ) from error
        if not members or any(
            not isinstance(item, str) or not item for item in members
        ):
            raise ValueError(
                "CHI coherence domain requires non-empty facet names"
            )
        object.__setattr__(self, "members", members)


@dataclass(frozen=True)
class ChiCoherenceAuthorityContract:
    """Construction intent joining address, Home, and domain facts."""

    authorities: tuple[ChiHomeAuthority, ...]
    domains: tuple[ChiCoherenceDomain, ...] = ()

    def __post_init__(self) -> None:
        authorities = tuple(self.authorities)
        domains = tuple(self.domains)
        if not authorities:
            raise ValueError(
                "CHI coherence authority contract requires an authority"
            )
        if any(
            not isinstance(item, ChiHomeAuthority) for item in authorities
        ):
            raise TypeError(
                "CHI coherence authority contract requires Home authorities"
            )
        if any(not isinstance(item, ChiCoherenceDomain) for item in domains):
            raise TypeError(
                "CHI coherence authority contract requires coherence domains"
            )
        object.__setattr__(self, "authorities", authorities)
        object.__setattr__(self, "domains", domains)


@dataclass(frozen=True)
class ChiResolvedCoherenceDomain:
    """Immutable coherence-domain membership with closed NodeID ownership."""

    name: str
    members: tuple[str, ...]
    node_id_by_member: Mapping[str, int]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("resolved CHI coherence domain requires a name")
        members = tuple(self.members)
        if not members or any(
            not isinstance(item, str) or not item for item in members
        ):
            raise ValueError(
                "resolved CHI coherence domain requires facet names"
            )
        if len(set(members)) != len(members):
            raise ValueError(
                "resolved CHI coherence domain members must be unique"
            )
        node_ids = dict(self.node_id_by_member)
        if set(node_ids) != set(members):
            raise ValueError(
                "resolved CHI coherence domain NodeIDs must cover members"
            )
        if any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 0
            for item in node_ids.values()
        ):
            raise ValueError(
                "resolved CHI coherence domain NodeIDs must be non-negative"
            )
        if len(set(node_ids.values())) != len(node_ids):
            raise ValueError(
                "resolved CHI coherence domain members require distinct "
                "NodeIDs"
            )
        object.__setattr__(self, "members", members)
        object.__setattr__(
            self,
            "node_id_by_member",
            MappingProxyType(node_ids),
        )


@dataclass(frozen=True)
class ChiResolvedHomeAuthority:
    """One address claim with its closed Home identity and domain."""

    address_claim: AddressClaim
    home: str
    home_node_id: int
    coherence_domain: ChiResolvedCoherenceDomain | None

    def __post_init__(self) -> None:
        if not isinstance(self.address_claim, AddressClaim):
            raise TypeError(
                "resolved CHI Home authority requires an AddressClaim"
            )
        if not isinstance(self.home, str) or not self.home:
            raise ValueError(
                "resolved CHI Home authority requires a Home facet name"
            )
        if (
            not isinstance(self.home_node_id, int)
            or isinstance(self.home_node_id, bool)
            or self.home_node_id < 0
        ):
            raise ValueError(
                "resolved CHI Home authority requires a non-negative NodeID"
            )
        if self.coherence_domain is not None and not isinstance(
            self.coherence_domain, ChiResolvedCoherenceDomain
        ):
            raise TypeError(
                "resolved CHI Home authority requires a resolved domain"
            )


@dataclass(frozen=True)
class ChiResolvedCoherenceAuthorityPlan:
    """Immutable address-to-Home and coherence-domain projection."""

    system: ElaboratedSystemProtocol
    authorities: tuple[ChiResolvedHomeAuthority, ...]
    domains: tuple[ChiResolvedCoherenceDomain, ...]
    authority_by_claim: Mapping[str, ChiResolvedHomeAuthority]
    domain_by_name: Mapping[str, ChiResolvedCoherenceDomain]

    def __post_init__(self) -> None:
        if not isinstance(self.system, ElaboratedSystemProtocol):
            raise TypeError(
                "resolved CHI coherence authority requires elaborated topology"
            )
        authorities = tuple(self.authorities)
        domains = tuple(self.domains)
        if not authorities or any(
            not isinstance(item, ChiResolvedHomeAuthority)
            for item in authorities
        ):
            raise TypeError(
                "resolved CHI authority plan requires Home authorities"
            )
        if any(
            not isinstance(item, ChiResolvedCoherenceDomain)
            for item in domains
        ):
            raise TypeError(
                "resolved CHI authority plan requires resolved domains"
            )
        authorities_by_claim = dict(self.authority_by_claim)
        expected_authorities = {
            item.address_claim.name: item for item in authorities
        }
        if (
            authorities_by_claim != expected_authorities
            or len(expected_authorities) != len(authorities)
        ):
            raise ValueError(
                "resolved CHI authority map must cover authorities exactly"
            )
        domains_by_name = dict(self.domain_by_name)
        expected_domains = {item.name: item for item in domains}
        if (
            domains_by_name != expected_domains
            or len(expected_domains) != len(domains)
        ):
            raise ValueError(
                "resolved CHI domain map must cover domains exactly"
            )
        object.__setattr__(self, "authorities", authorities)
        object.__setattr__(self, "domains", domains)
        object.__setattr__(
            self,
            "authority_by_claim",
            MappingProxyType(authorities_by_claim),
        )
        object.__setattr__(
            self,
            "domain_by_name",
            MappingProxyType(domains_by_name),
        )

    def authority_for_claim(
        self, claim: str
    ) -> ChiResolvedHomeAuthority:
        """Return the CHI authority assigned to an address claim."""

        if not isinstance(claim, str) or not claim:
            raise ValueError(
                "CHI Home authority lookup requires an address claim name"
            )
        try:
            return self.authority_by_claim[claim]
        except KeyError as error:
            raise KeyError(
                f"address claim {claim!r} has no CHI Home authority"
            ) from error

    def authority_for_address(
        self,
        address: int,
        size_bytes: int = 1,
    ) -> ChiResolvedHomeAuthority:
        """Return the unique Home authority covering an address window."""

        query = AddressWindow(address, size_bytes)
        matches = tuple(
            item
            for item in self.authorities
            if item.address_claim.window.contains(query)
        )
        if not matches:
            raise KeyError(
                "address window "
                f"0x{query.base_address:x}+0x{query.size_bytes:x} "
                "has no CHI Home authority"
            )
        if len(matches) != 1:
            raise RuntimeError(
                "resolved CHI Home authority windows are ambiguous"
            )
        return matches[0]

    def domain_for_claim(
        self, claim: str
    ) -> ChiResolvedCoherenceDomain | None:
        """Return the coherence domain assigned to an address claim."""

        return self.authority_for_claim(claim).coherence_domain

    def eligible_snoopees(
        self,
        claim: str,
        requester: str,
    ) -> tuple[str, ...]:
        """Derive finite Snoopees from domain membership for one Requester."""

        if not isinstance(requester, str) or not requester:
            raise ValueError(
                "eligible Snoopee lookup requires a Requester facet name"
            )
        domain = self.domain_for_claim(claim)
        if domain is None:
            return ()
        if requester not in domain.members:
            raise ValueError(
                f"Requester {requester!r} is not a member of coherence "
                f"domain {domain.name!r}"
            )
        return tuple(
            member for member in domain.members if member != requester
        )


def resolve_chi_coherence_authority(
    system: ElaboratedSystemProtocol,
    facets: tuple[ChiBehaviorFacet, ...],
    identities: ChiResolvedIdentityPlan,
    contract: ChiCoherenceAuthorityContract,
) -> ChiResolvedCoherenceAuthorityPlan:
    """Close CHI Home authority against address, facet, and identity plans."""

    if not isinstance(system, ElaboratedSystemProtocol):
        raise TypeError(
            "CHI coherence authority resolution requires elaborated topology"
        )
    if system.address_plan is None:
        raise ValueError(
            "CHI coherence authority resolution requires an address plan"
        )
    facet_items = tuple(facets)
    if any(not isinstance(item, ChiBehaviorFacet) for item in facet_items):
        raise TypeError(
            "CHI coherence authority resolution requires behavior facets"
        )
    if not isinstance(identities, ChiResolvedIdentityPlan):
        raise TypeError(
            "CHI coherence authority resolution requires an identity plan"
        )
    if identities.system != system.spec.name:
        raise ValueError(
            "CHI identity and coherence authority plans must use the same system"
        )
    identities.require_closed()
    if not isinstance(contract, ChiCoherenceAuthorityContract):
        raise TypeError(
            "CHI coherence authority resolution requires an authority contract"
        )

    facets_by_name: dict[str, ChiBehaviorFacet] = {}
    for facet in facet_items:
        if facet.name in facets_by_name:
            raise ValueError(
                "CHI coherence authority facet names must be globally unique: "
                f"{facet.name!r}"
            )
        facets_by_name[facet.name] = facet

    domain_names = tuple(item.name for item in contract.domains)
    if len(set(domain_names)) != len(domain_names):
        raise ValueError("CHI coherence domain names must be unique")
    resolved_domains: list[ChiResolvedCoherenceDomain] = []
    domain_by_name: dict[str, ChiResolvedCoherenceDomain] = {}
    for domain in contract.domains:
        members = tuple(sorted(domain.members))
        node_id_by_member: dict[str, int] = {}
        for member in members:
            facet, node_id, _identity = _require_transaction_identity(
                member,
                facets_by_name,
                identities,
                subject=f"coherence domain {domain.name!r} member",
            )
            assert facet.name == member
            node_id_by_member[member] = node_id
        resolved = ChiResolvedCoherenceDomain(
            domain.name,
            members,
            node_id_by_member,
        )
        resolved_domains.append(resolved)
        domain_by_name[resolved.name] = resolved

    authority_claims = tuple(
        item.address_claim for item in contract.authorities
    )
    if len(set(authority_claims)) != len(authority_claims):
        raise ValueError(
            "each address claim may have only one CHI Home authority"
        )

    resolved_authorities: list[ChiResolvedHomeAuthority] = []
    for authority in contract.authorities:
        try:
            claim = system.address_plan.claims_by_name[
                authority.address_claim
            ]
        except KeyError as error:
            raise ValueError(
                f"CHI Home authority references unknown address claim "
                f"{authority.address_claim!r}"
            ) from error
        if any(
            path.claim.name == claim.name
            for path in system.address_plan.paths
        ):
            raise ValueError(
                f"CHI Home authority claim {claim.name!r} participates in "
                "an address-router path; the current profile requires an "
                "untranslated feature address scope until SAM projection "
                "can derive the system-visible window"
            )
        home_facet, home_node_id, home_identity = (
            _require_transaction_identity(
                authority.home,
                facets_by_name,
                identities,
                subject="CHI Home authority",
            )
        )
        if claim.endpoint not in home_identity.ports:
            raise ValueError(
                f"address claim {claim.name!r} endpoint "
                f"{claim.endpoint.qualified_name!r} is not part of Home "
                f"identity boundary for facet {home_facet.name!r}"
            )
        if authority.coherence_domain is None:
            domain = None
        else:
            try:
                domain = domain_by_name[authority.coherence_domain]
            except KeyError as error:
                raise ValueError(
                    f"CHI Home authority for claim {claim.name!r} references "
                    f"unknown coherence domain "
                    f"{authority.coherence_domain!r}"
                ) from error
            if authority.home in domain.members:
                raise ValueError(
                    f"Home facet {authority.home!r} must not be a member of "
                    f"its coherence domain {domain.name!r}"
                )
            if home_node_id in domain.node_id_by_member.values():
                raise ValueError(
                    f"Home NodeID {home_node_id} must not be owned by a "
                    f"member of coherence domain {domain.name!r}"
                )
        resolved_authorities.append(
            ChiResolvedHomeAuthority(
                claim,
                authority.home,
                home_node_id,
                domain,
            )
        )

    ordered_by_window = sorted(
        resolved_authorities,
        key=lambda item: item.address_claim.window.base_address,
    )
    for previous, current in zip(
        ordered_by_window, ordered_by_window[1:]
    ):
        if previous.address_claim.window.overlaps(
            current.address_claim.window
        ):
            raise ValueError(
                f"CHI Home authority address claims "
                f"{previous.address_claim.name!r} and "
                f"{current.address_claim.name!r} overlap"
            )

    return ChiResolvedCoherenceAuthorityPlan(
        system,
        tuple(resolved_authorities),
        tuple(resolved_domains),
        {
            item.address_claim.name: item
            for item in resolved_authorities
        },
        domain_by_name,
    )


def _require_transaction_identity(
    name: str,
    facets_by_name: Mapping[str, ChiBehaviorFacet],
    identities: ChiResolvedIdentityPlan,
    *,
    subject: str,
) -> tuple[ChiBehaviorFacet, int, ChiResolvedNodeIdentity]:
    try:
        facet = facets_by_name[name]
    except KeyError as error:
        raise ValueError(
            f"{subject} references unknown facet {name!r}"
        ) from error
    if facet.kind is not ChiFacetKind.TRANSACTION:
        raise ValueError(
            f"{subject} {name!r} must reference a transaction facet"
        )
    if len(facet.node_ids) != 1:
        raise ValueError(
            f"{subject} {name!r} must resolve to exactly one NodeID"
        )
    node_id = next(iter(facet.node_ids))
    try:
        identity = identities.owner_by_node_id[node_id]
    except KeyError as error:
        raise ValueError(
            f"{subject} {name!r} NodeID {node_id} is not resolved"
        ) from error
    if facet.qualified_name not in identity.facets:
        raise ValueError(
            f"{subject} {name!r} does not own its resolved NodeID"
        )
    return facet, node_id, identity


__all__ = [
    "ChiCoherenceAuthorityContract",
    "ChiCoherenceDomain",
    "ChiHomeAuthority",
    "ChiResolvedCoherenceAuthorityPlan",
    "ChiResolvedCoherenceDomain",
    "ChiResolvedHomeAuthority",
    "resolve_chi_coherence_authority",
]
