"""Attach restricted CHI Issue H coherence to a cache storage core.

Construction starts with protocol-neutral resident-line storage.  The CHI
participant adds permission, Snoop, transaction, and channel behavior; it does
not create the cache's data store.  The resulting assembly shares one store
between the cache identity and the CHI behavior facet.

This is a cache controller at CHI-visible depth.  It does not imply a tag-array
geometry, replacement policy, local CPU pipeline, MMU, or a particular RTL
MSHR implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentRnNode,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
    ChiVirtualDutFacets,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)
from protocol_model.virtual_dut.backend.cache import (
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
)


@dataclass(frozen=True)
class ChiIssueHCacheVdutAssembly:
    """One concrete cache VirtualDut plus its CHI transaction behavior.

    ``virtual_dut`` is the module/topology identity.  ``cache_core`` owns
    resident line data.  ``participant`` adds CHI permission and finite
    coherent-transaction state.  ``facets`` is the family-local binding
    consumed by CHI construction and runtimes.
    """

    virtual_dut: VirtualDut
    cache_core: CacheCore[CacheLinePayload]
    participant: ChiCoherentRnNode
    facets: ChiVirtualDutFacets

    def __post_init__(self) -> None:
        if not isinstance(self.virtual_dut, VirtualDut):
            raise TypeError("CHI cache assembly requires a VirtualDut")
        if not isinstance(self.cache_core, CacheCore):
            raise TypeError(
                "CHI cache assembly requires a CacheCore"
            )
        if not isinstance(self.participant, ChiCoherentRnNode):
            raise TypeError(
                "CHI cache assembly requires a coherent RN participant"
            )
        if self.participant.cache_core is not self.cache_core:
            raise ValueError(
                "CHI cache participant must use the assembled cache core"
            )
        if not isinstance(self.facets, ChiVirtualDutFacets):
            raise TypeError("CHI cache assembly requires CHI behavior facets")
        if self.facets.dut is not self.virtual_dut:
            raise ValueError(
                "CHI cache facets must bind the assembled VirtualDut"
            )
        if len(self.facets.facets) != 1:
            raise ValueError(
                "the current CHI cache recipe requires one transaction facet"
            )
        facet = self.facets.facets[0]
        if facet.kind is not ChiFacetKind.TRANSACTION:
            raise ValueError(
                "the CHI cache behavior must be a transaction facet"
            )
        if facet.component is not self.participant:
            raise ValueError(
                "CHI cache facet must use the assembled participant"
            )

    @property
    def binding(self) -> ChiParticipantBinding:
        """Return the compatibility binding consumed by current sessions."""

        return self.facets.facets[0].binding

    @property
    def cache_store(self) -> CacheLineStore[CacheLinePayload]:
        """Project the storage leaf retained by the cache core."""

        return self.cache_core.line_store


def attach_chi_issue_h_coherence(
    name: str,
    cache_core: CacheCore[CacheLinePayload],
    node_id: int,
    home_node_id: int,
    *,
    initial_permissions: Mapping[int, ChiCacheState],
    coherence_transaction_capacity: int = 4,
    transmit_port_name: str = "chi_tx",
    receive_port_name: str = "chi_rx",
    clock_domain: str | None = None,
    reset_domain: str | None = None,
) -> ChiIssueHCacheVdutAssembly:
    """Attach CHI behavior to an already selected cache storage core.

    The two transport ports are directionally explicit:

    - transmit: REQ, RSP, and DAT;
    - receive: RSP, SNP, and DAT.

    The receive RSP channel is included even though the current executable
    coherent-read slice completes with DAT.  It is required by dataless
    completion and Retry lifecycles, so the module boundary does not need to be
    rebuilt when those participant methods are added.

    ``coherence_transaction_capacity`` bounds the currently implemented RN
    pending table.  It is a semantic capacity for outstanding coherent
    lifecycles, not a claim about an RTL MSHR array or cache geometry.
    """

    if not isinstance(cache_core, CacheCore):
        raise TypeError(
            "CHI coherence attachment requires CacheCore"
        )
    tx = TransportPort(
        transmit_port_name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        TransportDirection.TRANSMIT,
        clock_domain=clock_domain,
        reset_domain=reset_domain,
    )
    rx = TransportPort(
        receive_port_name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        TransportDirection.RECEIVE,
        clock_domain=clock_domain,
        reset_domain=reset_domain,
    )
    virtual_dut = VirtualDut(
        name,
        {
            tx.name: tx,
            rx.name: rx,
        },
        behavior_tags=frozenset((DutBehaviorTag.INITIATING,)),
        description=(
            "CHI Issue H coherent cache participant at protocol-visible depth"
        ),
    )
    participant = ChiCoherentRnNode(
        f"{name}.coherence",
        node_id,
        home_node_id,
        cache_core=cache_core,
        initial_permissions=initial_permissions,
        outstanding_capacity=coherence_transaction_capacity,
    )
    binding = ChiParticipantBinding(
        f"{name}.chi",
        virtual_dut,
        participant,
        (
            ChiParticipantPortBinding(
                tx,
                frozenset(
                    (
                        ChiChannelKind.REQ,
                        ChiChannelKind.RSP,
                        ChiChannelKind.DAT,
                    )
                ),
            ),
            ChiParticipantPortBinding(
                rx,
                frozenset(
                    (
                        ChiChannelKind.RSP,
                        ChiChannelKind.SNP,
                        ChiChannelKind.DAT,
                    )
                ),
            ),
        ),
        frozenset((node_id,)),
    )
    facet = ChiBehaviorFacet.from_binding(
        binding,
        ChiFacetKind.TRANSACTION,
    )
    return ChiIssueHCacheVdutAssembly(
        virtual_dut,
        cache_core,
        participant,
        ChiVirtualDutFacets(virtual_dut, (facet,)),
    )


def build_chi_issue_h_cache_vdut(
    name: str,
    node_id: int,
    home_node_id: int,
    *,
    initial_lines: tuple[ChiCacheLine, ...] = (),
    coherence_transaction_capacity: int = 4,
    transmit_port_name: str = "chi_tx",
    receive_port_name: str = "chi_rx",
    clock_domain: str | None = None,
    reset_domain: str | None = None,
) -> ChiIssueHCacheVdutAssembly:
    """Convenience composition of a cache store followed by CHI attachment.

    Call :func:`attach_chi_issue_h_coherence` directly when a cache core is
    created elsewhere or needs a custom capacity/replacement refinement.
    """

    lines = tuple(initial_lines)
    if any(not isinstance(item, ChiCacheLine) for item in lines):
        raise TypeError("CHI cache initial lines require ChiCacheLine")
    if len({item.address for item in lines}) != len(lines):
        raise ValueError(
            "CHI cache initial line addresses must be unique"
        )
    cache_store = CacheLineStore(
        f"{name}.cache.lines",
        line_bytes=64,
        initial_lines=tuple(
            CacheLinePayload(item.address, item.data)
            for item in lines
            if item.state is not ChiCacheState.I and item.data is not None
        ),
    )
    cache_core = CacheCore(f"{name}.cache", cache_store)
    return attach_chi_issue_h_coherence(
        name,
        cache_core,
        node_id,
        home_node_id,
        initial_permissions={
            item.address: item.state
            for item in lines
        },
        coherence_transaction_capacity=coherence_transaction_capacity,
        transmit_port_name=transmit_port_name,
        receive_port_name=receive_port_name,
        clock_domain=clock_domain,
        reset_domain=reset_domain,
    )


def build_chi_cache_participant_fixture(
    name: str,
    node_id: int,
    home_node_id: int,
    *,
    initial_lines: tuple[ChiCacheLine, ...] = (),
    outstanding_capacity: int = 4,
) -> ChiCoherentRnNode:
    """Return only the participant projection of a cache-first assembly.

    This convenience is intended for participant lifecycle tests and compact
    scenarios.  Code that needs the module boundary or topology identity
    should retain the :class:`ChiIssueHCacheVdutAssembly` returned by
    :func:`build_chi_issue_h_cache_vdut`.
    """

    return build_chi_issue_h_cache_vdut(
        name,
        node_id,
        home_node_id,
        initial_lines=initial_lines,
        coherence_transaction_capacity=outstanding_capacity,
    ).participant


__all__ = [
    "ChiIssueHCacheVdutAssembly",
    "attach_chi_issue_h_coherence",
    "build_chi_cache_participant_fixture",
    "build_chi_issue_h_cache_vdut",
]
