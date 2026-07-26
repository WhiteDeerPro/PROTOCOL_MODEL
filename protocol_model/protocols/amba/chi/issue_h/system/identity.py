"""CHI-family NodeID ownership closure over an elaborated system topology.

The generic SystemProtocol owns modules, ports, directed connections, and port
ownership.  CHI-specific NodeID meaning remains in this leaf package.  This
resolver joins those two views without making the generic system import CHI or
mutating a VirtualDut.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.system.elaboration import ElaboratedSystemProtocol
from protocol_model.system.topology.model import VirtualDutPortRef

from ..participants.facet import (
    ChiBehaviorFacet,
    ChiFacetKind,
    ChiNodeIdOffer,
)


class ChiIdentityIssueSeverity(str, Enum):
    """Whether an identity issue is missing intent or contradictory intent."""

    GAP = "gap"
    ERROR = "error"


class ChiIdentityIssueCode(str, Enum):
    """Stable machine-readable categories emitted by identity resolution."""

    MISSING_PARTICIPANT_IDENTITY = "missing_participant_identity"
    UNKNOWN_DUT = "unknown_dut"
    NONCANONICAL_DUT = "noncanonical_dut"
    PORT_NOT_IN_TOPOLOGY = "port_not_in_topology"
    DUPLICATE_FACET_NAME = "duplicate_facet_name"
    AMBIGUOUS_NODE_ID = "ambiguous_node_id"
    INVALID_SHARED_NODE_ID = "invalid_shared_node_id"


@dataclass(frozen=True)
class ChiIdentityIssue:
    """One structured gap or contradiction in CHI NodeID intent."""

    severity: ChiIdentityIssueSeverity
    code: ChiIdentityIssueCode
    message: str
    node_id: int | None = None
    facets: tuple[str, ...] = ()
    ports: tuple[VirtualDutPortRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.severity, ChiIdentityIssueSeverity):
            raise TypeError("CHI identity issue requires a severity")
        if not isinstance(self.code, ChiIdentityIssueCode):
            raise TypeError("CHI identity issue requires a code")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("CHI identity issue requires a message")
        if self.node_id is not None and (
            not isinstance(self.node_id, int)
            or isinstance(self.node_id, bool)
            or self.node_id < 0
        ):
            raise ValueError("CHI identity issue NodeID must be non-negative")
        facets = tuple(self.facets)
        ports = tuple(self.ports)
        if any(not isinstance(item, str) or not item for item in facets):
            raise ValueError("CHI identity issue facet names must be non-empty")
        if any(not isinstance(item, VirtualDutPortRef) for item in ports):
            raise TypeError("CHI identity issue ports require VirtualDutPortRef")
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "ports", ports)


@dataclass(frozen=True)
class ChiResolvedNodeIdentity:
    """Unique or explicitly shared ownership of one CHI NodeID."""

    node_id: int
    dut: str
    facets: tuple[str, ...]
    ports: tuple[VirtualDutPortRef, ...]
    shared: bool = False
    share_group: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id, int)
            or isinstance(self.node_id, bool)
            or self.node_id < 0
        ):
            raise ValueError("resolved CHI NodeID must be non-negative")
        if not isinstance(self.dut, str) or not self.dut:
            raise ValueError("resolved CHI NodeID requires a VirtualDut name")
        facets = tuple(self.facets)
        ports = tuple(self.ports)
        if not facets or any(
            not isinstance(item, str) or not item for item in facets
        ):
            raise ValueError(
                "resolved CHI NodeID requires non-empty facet names"
            )
        if not ports or any(
            not isinstance(item, VirtualDutPortRef) for item in ports
        ):
            raise TypeError(
                "resolved CHI NodeID requires VirtualDutPortRef values"
            )
        if any(item.dut != self.dut for item in ports):
            raise ValueError(
                "resolved CHI NodeID ports must belong to its VirtualDut"
            )
        if self.shared:
            if (
                not isinstance(self.share_group, str)
                or not self.share_group
                or len(facets) < 2
            ):
                raise ValueError(
                    "shared CHI NodeID requires a share group and two facets"
                )
        elif self.share_group is not None and (
            not isinstance(self.share_group, str) or not self.share_group
        ):
            raise ValueError(
                "resolved CHI NodeID share group must be non-empty or None"
            )
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "ports", ports)


@dataclass(frozen=True)
class ChiResolvedIdentityPlan:
    """Immutable NodeID ownership projection plus structured closure issues."""

    system: str
    identities: tuple[ChiResolvedNodeIdentity, ...]
    owner_by_node_id: Mapping[int, ChiResolvedNodeIdentity]
    issues: tuple[ChiIdentityIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.system, str) or not self.system:
            raise ValueError("CHI identity plan requires a system name")
        identities = tuple(self.identities)
        issues = tuple(self.issues)
        if any(
            not isinstance(item, ChiResolvedNodeIdentity) for item in identities
        ):
            raise TypeError(
                "CHI identity plan requires resolved identity values"
            )
        if any(not isinstance(item, ChiIdentityIssue) for item in issues):
            raise TypeError("CHI identity plan issues require ChiIdentityIssue")
        owners = dict(self.owner_by_node_id)
        expected = {item.node_id: item for item in identities}
        if owners != expected or len(expected) != len(identities):
            raise ValueError(
                "CHI identity owner map must cover resolved NodeIDs exactly"
            )
        object.__setattr__(self, "identities", identities)
        object.__setattr__(
            self, "owner_by_node_id", MappingProxyType(owners)
        )
        object.__setattr__(self, "issues", issues)

    @property
    def gaps(self) -> tuple[ChiIdentityIssue, ...]:
        return tuple(
            item
            for item in self.issues
            if item.severity is ChiIdentityIssueSeverity.GAP
        )

    @property
    def errors(self) -> tuple[ChiIdentityIssue, ...]:
        return tuple(
            item
            for item in self.issues
            if item.severity is ChiIdentityIssueSeverity.ERROR
        )

    @property
    def is_closed(self) -> bool:
        return not self.issues

    def require_closed(self) -> "ChiResolvedIdentityPlan":
        """Return this plan or raise an exception carrying structured issues."""

        if self.issues:
            raise ChiIdentityResolutionError(self.issues)
        return self


class ChiIdentityResolutionError(ValueError):
    """Identity closure failure retaining machine-readable issue values."""

    def __init__(self, issues: tuple[ChiIdentityIssue, ...]) -> None:
        issue_items = tuple(issues)
        if not issue_items or any(
            not isinstance(item, ChiIdentityIssue) for item in issue_items
        ):
            raise TypeError(
                "CHI identity resolution error requires identity issues"
            )
        self.issues = issue_items
        super().__init__("; ".join(item.message for item in issue_items))


@dataclass(frozen=True)
class _IdentityClaim:
    facet: ChiBehaviorFacet
    offer: ChiNodeIdOffer
    node_id: int
    ports: tuple[VirtualDutPortRef, ...]


def resolve_chi_node_identities(
    system: ElaboratedSystemProtocol,
    facets: tuple[ChiBehaviorFacet, ...],
) -> ChiResolvedIdentityPlan:
    """Resolve unique NodeID ownership from CHI facet and port offers.

    A duplicate NodeID is rejected by default.  It is accepted only when every
    claimant names the same non-empty share group and all claims refer to the
    same concrete VirtualDut and exact logical port set.
    """

    if not isinstance(system, ElaboratedSystemProtocol):
        raise TypeError(
            "CHI identity resolution requires ElaboratedSystemProtocol"
        )
    facet_items = tuple(facets)
    if any(not isinstance(item, ChiBehaviorFacet) for item in facet_items):
        raise TypeError(
            "CHI identity resolution requires ChiBehaviorFacet values"
        )

    issues: list[ChiIdentityIssue] = []
    claims_by_node_id: dict[int, list[_IdentityClaim]] = {}
    facets_by_name: dict[str, list[ChiBehaviorFacet]] = {}
    for facet in facet_items:
        facets_by_name.setdefault(facet.qualified_name, []).append(facet)
    duplicate_names = {
        name for name, entries in facets_by_name.items() if len(entries) > 1
    }
    for name in sorted(duplicate_names):
        issues.append(
            ChiIdentityIssue(
                ChiIdentityIssueSeverity.ERROR,
                ChiIdentityIssueCode.DUPLICATE_FACET_NAME,
                f"CHI behavior facet {name!r} is declared more than once",
                facets=(name,),
            )
        )

    for facet in facet_items:
        if facet.qualified_name in duplicate_names:
            continue
        canonical = system.spec.virtual_duts.get(facet.dut.name)
        if canonical is None:
            issues.append(
                ChiIdentityIssue(
                    ChiIdentityIssueSeverity.ERROR,
                    ChiIdentityIssueCode.UNKNOWN_DUT,
                    f"CHI facet {facet.qualified_name!r} references a "
                    "VirtualDut outside the elaborated system",
                    facets=(facet.qualified_name,),
                )
            )
            continue
        if canonical is not facet.dut:
            issues.append(
                ChiIdentityIssue(
                    ChiIdentityIssueSeverity.ERROR,
                    ChiIdentityIssueCode.NONCANONICAL_DUT,
                    f"CHI facet {facet.qualified_name!r} does not reference "
                    "the canonical VirtualDut object in the system",
                    facets=(facet.qualified_name,),
                )
            )
            continue
        if (
            facet.kind is ChiFacetKind.TRANSACTION
            and not facet.identity_offers
        ):
            issues.append(
                ChiIdentityIssue(
                    ChiIdentityIssueSeverity.GAP,
                    ChiIdentityIssueCode.MISSING_PARTICIPANT_IDENTITY,
                    f"transaction facet {facet.qualified_name!r} has no "
                    "NodeID offer",
                    facets=(facet.qualified_name,),
                )
            )
        for offer in facet.identity_offers:
            ports = tuple(
                sorted(
                    (
                        VirtualDutPortRef(facet.dut.name, port)
                        for port in offer.ports
                    ),
                    key=lambda item: item.qualified_name,
                )
            )
            missing = tuple(
                port for port in ports if port not in system.owner_by_port
            )
            if missing:
                issues.append(
                    ChiIdentityIssue(
                        ChiIdentityIssueSeverity.ERROR,
                        ChiIdentityIssueCode.PORT_NOT_IN_TOPOLOGY,
                        f"CHI facet {facet.qualified_name!r} offers NodeIDs "
                        "on ports absent from elaborated topology ownership",
                        facets=(facet.qualified_name,),
                        ports=missing,
                    )
                )
                continue
            for node_id in sorted(offer.node_ids):
                claims_by_node_id.setdefault(node_id, []).append(
                    _IdentityClaim(facet, offer, node_id, ports)
                )

    identities: list[ChiResolvedNodeIdentity] = []
    for node_id, claims in sorted(claims_by_node_id.items()):
        if len(claims) == 1:
            claim = claims[0]
            identities.append(
                ChiResolvedNodeIdentity(
                    node_id,
                    claim.facet.dut.name,
                    (claim.facet.qualified_name,),
                    claim.ports,
                    share_group=claim.offer.share_group,
                )
            )
            continue

        facet_names = tuple(
            sorted(claim.facet.qualified_name for claim in claims)
        )
        all_ports = tuple(
            sorted(
                {port for claim in claims for port in claim.ports},
                key=lambda item: item.qualified_name,
            )
        )
        physical_boundaries = {
            (
                claim.facet.dut.name,
                tuple(port.port for port in claim.ports),
            )
            for claim in claims
        }
        share_groups = {claim.offer.share_group for claim in claims}
        explicitly_shared = (
            len(share_groups) == 1 and None not in share_groups
        )
        if explicitly_shared and len(physical_boundaries) == 1:
            first = claims[0]
            share_group = first.offer.share_group
            assert share_group is not None
            identities.append(
                ChiResolvedNodeIdentity(
                    node_id,
                    first.facet.dut.name,
                    facet_names,
                    first.ports,
                    shared=True,
                    share_group=share_group,
                )
            )
            continue

        invalid_share = any(
            claim.offer.share_group is not None for claim in claims
        )
        code = (
            ChiIdentityIssueCode.INVALID_SHARED_NODE_ID
            if invalid_share
            else ChiIdentityIssueCode.AMBIGUOUS_NODE_ID
        )
        if invalid_share:
            reason = (
                "explicit NodeID sharing requires the same non-empty share "
                "group, VirtualDut, and exact port set for every claimant"
            )
        else:
            reason = (
                "multiple facets offer the same NodeID without explicit sharing"
            )
        issues.append(
            ChiIdentityIssue(
                ChiIdentityIssueSeverity.ERROR,
                code,
                f"NodeID {node_id} is ambiguous: {reason}",
                node_id=node_id,
                facets=facet_names,
                ports=all_ports,
            )
        )

    identities.sort(key=lambda item: item.node_id)
    return ChiResolvedIdentityPlan(
        system.spec.name,
        tuple(identities),
        {item.node_id: item for item in identities},
        tuple(issues),
    )


__all__ = [
    "ChiIdentityIssue",
    "ChiIdentityIssueCode",
    "ChiIdentityIssueSeverity",
    "ChiIdentityResolutionError",
    "ChiResolvedIdentityPlan",
    "ChiResolvedNodeIdentity",
    "resolve_chi_node_identities",
]
