"""Composable CHI behavior facets on one concrete VirtualDut boundary.

The current executable slices historically use :class:`ChiParticipantBinding`
for Requester, Home, and router behavior alike.  This module adds a small
family-local description that distinguishes transaction participation from
network forwarding without creating RN/HN/SN class hierarchies or changing the
existing runtime binding.

NodeID offers are attached to a named set of transport ports.  The set denotes
one logical CHI identity boundary and can therefore contain several
unidirectional ``TransportPort`` objects.  Sharing one NodeID between facets is
not implied by using the same VirtualDut or ports; it requires an explicit
``share_group`` and is decided by the system identity resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from protocol_model.semantics import SemanticComponent
from protocol_model.virtual_dut.boundary.module import VirtualDut

from .binding import ChiParticipantBinding, ChiParticipantPortBinding


class ChiFacetKind(str, Enum):
    """Purpose of one independently composable CHI behavior facet."""

    TRANSACTION = "transaction"
    FORWARDING = "forwarding"


@dataclass(frozen=True)
class ChiNodeIdOffer:
    """NodeIDs offered on one logical port boundary of a behavior facet.

    ``ports`` contains concrete ``TransportPort`` names from the enclosing
    facet binding.  Multiple names are useful because this repository models
    CHI transport endpoints as unidirectional ports, while one CHI identity can
    be visible through several channel/direction endpoints.

    ``share_group`` is only an opt-in declaration.  The system resolver also
    requires every claimant to name the same VirtualDut and exact port set
    before accepting shared ownership.
    """

    node_ids: frozenset[int]
    ports: frozenset[str]
    share_group: str | None = None

    def __post_init__(self) -> None:
        try:
            node_ids = frozenset(self.node_ids)
        except TypeError as error:
            raise TypeError("CHI NodeID offer values must be iterable") from error
        if not node_ids:
            raise ValueError("CHI NodeID offer requires at least one NodeID")
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in node_ids
        ):
            raise ValueError("CHI NodeID offers require non-negative integers")
        try:
            ports = frozenset(self.ports)
        except TypeError as error:
            raise TypeError("CHI NodeID offer ports must be iterable") from error
        if not ports or any(
            not isinstance(item, str) or not item for item in ports
        ):
            raise ValueError(
                "CHI NodeID offer requires non-empty transport port names"
            )
        if self.share_group is not None and (
            not isinstance(self.share_group, str) or not self.share_group
        ):
            raise ValueError(
                "CHI NodeID share group must be a non-empty string or None"
            )
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "ports", ports)


@dataclass(frozen=True)
class ChiBehaviorFacet:
    """One transaction or forwarding behavior on a concrete VirtualDut.

    The wrapped :class:`ChiParticipantBinding` remains the compatibility
    projection consumed by the current read/retry/network runtimes.  The facet
    adds composition purpose and explicit identity-to-port offers without
    changing that established executable object.
    """

    kind: ChiFacetKind
    binding: ChiParticipantBinding
    identity_offers: tuple[ChiNodeIdOffer, ...] = ()

    def __post_init__(self) -> None:
        try:
            kind = ChiFacetKind(self.kind)
        except (TypeError, ValueError) as error:
            raise ValueError("CHI behavior facet requires a known kind") from error
        if not isinstance(self.binding, ChiParticipantBinding):
            raise TypeError(
                "CHI behavior facet requires ChiParticipantBinding"
            )
        offers = tuple(self.identity_offers)
        if any(not isinstance(item, ChiNodeIdOffer) for item in offers):
            raise TypeError(
                "CHI behavior facet identity offers require ChiNodeIdOffer"
            )
        port_names = {item.port.name for item in self.binding.ports}
        unknown_ports = {
            port
            for offer in offers
            for port in offer.ports
            if port not in port_names
        }
        if unknown_ports:
            raise ValueError(
                f"CHI facet identity offers reference unbound ports: "
                f"{sorted(unknown_ports)!r}"
            )
        offered_ids = tuple(
            node_id for offer in offers for node_id in offer.node_ids
        )
        if len(set(offered_ids)) != len(offered_ids):
            raise ValueError(
                "one CHI behavior facet cannot offer a NodeID twice"
            )
        if frozenset(offered_ids) != self.binding.node_ids:
            raise ValueError(
                "CHI facet identity offers must cover exactly the NodeIDs "
                "declared by its compatibility binding"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "identity_offers", offers)

    @classmethod
    def from_binding(
        cls,
        binding: ChiParticipantBinding,
        kind: ChiFacetKind,
        *,
        identity_ports: frozenset[str] | None = None,
        share_group: str | None = None,
    ) -> "ChiBehaviorFacet":
        """Project one established runtime binding into the facet model.

        Existing NodeIDs are offered on all bound ports unless the caller names
        a smaller logical identity boundary.  No sharing is enabled by default.
        """

        if not isinstance(binding, ChiParticipantBinding):
            raise TypeError(
                "CHI facet projection requires ChiParticipantBinding"
            )
        if not binding.node_ids:
            if identity_ports is not None:
                raise ValueError(
                    "a binding without NodeIDs cannot select identity ports"
                )
            if share_group is not None:
                raise ValueError(
                    "a binding without NodeIDs cannot declare identity sharing"
                )
            offers: tuple[ChiNodeIdOffer, ...] = ()
        else:
            ports = (
                frozenset(item.port.name for item in binding.ports)
                if identity_ports is None
                else frozenset(identity_ports)
            )
            offers = (ChiNodeIdOffer(binding.node_ids, ports, share_group),)
        return cls(kind, binding, offers)

    @property
    def name(self) -> str:
        return self.binding.name

    @property
    def qualified_name(self) -> str:
        return f"{self.dut.name}:{self.name}"

    @property
    def dut(self) -> VirtualDut:
        return self.binding.dut

    @property
    def component(self) -> SemanticComponent:
        return self.binding.component

    @property
    def ports(self) -> tuple[ChiParticipantPortBinding, ...]:
        return self.binding.ports

    @property
    def node_ids(self) -> frozenset[int]:
        return self.binding.node_ids

    def as_participant_binding(self) -> ChiParticipantBinding:
        """Return the unchanged object used by existing executable sessions."""

        return self.binding


@dataclass(frozen=True)
class ChiVirtualDutFacets:
    """A composition of independent CHI facets on one concrete module."""

    dut: VirtualDut
    facets: tuple[ChiBehaviorFacet, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dut, VirtualDut):
            raise TypeError("CHI facet composition requires VirtualDut")
        facets = tuple(self.facets)
        if not facets:
            raise ValueError("CHI facet composition requires at least one facet")
        if any(not isinstance(item, ChiBehaviorFacet) for item in facets):
            raise TypeError(
                "CHI facet composition requires ChiBehaviorFacet values"
            )
        if any(item.dut is not self.dut for item in facets):
            raise ValueError(
                "every CHI facet in a composition must use the same VirtualDut"
            )
        names = tuple(item.name for item in facets)
        if len(set(names)) != len(names):
            raise ValueError(
                "CHI facets on one VirtualDut require unique binding names"
            )
        object.__setattr__(self, "facets", facets)

    def of_kind(self, kind: ChiFacetKind) -> tuple[ChiBehaviorFacet, ...]:
        kind = ChiFacetKind(kind)
        return tuple(item for item in self.facets if item.kind is kind)


__all__ = [
    "ChiBehaviorFacet",
    "ChiFacetKind",
    "ChiNodeIdOffer",
    "ChiVirtualDutFacets",
]
