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


def bind_chi_issue_h_cache_vdut(
    virtual_dut: VirtualDut,
    cache_core: CacheCore[CacheLinePayload],
    node_id: int,
    home_node_id: int,
    *,
    port_channels: Mapping[str, frozenset[ChiChannelKind]],
    initial_permissions: Mapping[int, ChiCacheState],
    participant_name: str | None = None,
    binding_name: str | None = None,
    coherence_transaction_capacity: int = 4,
) -> ChiIssueHCacheVdutAssembly:
    """Bind an existing cache core to one existing VirtualDut boundary.

    This function does not create ports or connect them to a topology.  It
    projects selected ports of ``virtual_dut`` into one CHI transaction facet;
    the caller remains responsible for adding that same object to
    ``SystemProtocol`` and connecting its transport ports.

    The mapping is role/profile-specific.  A Requester-only construction may
    expose fewer channels than a cache that is also eligible as a Snoopee;
    later feature/capability closure decides whether the selected boundary is
    sufficient for the requested lifecycle.
    """

    if not isinstance(virtual_dut, VirtualDut):
        raise TypeError(
            "CHI coherence binding requires an existing VirtualDut"
        )
    if not isinstance(cache_core, CacheCore):
        raise TypeError("CHI coherence binding requires CacheCore")
    try:
        declared_channels = dict(port_channels)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "CHI coherence port_channels requires a port-to-channel mapping"
        ) from error
    try:
        channels_by_port = {
            name: frozenset(
                ChiChannelKind(channel) for channel in channels
            )
            for name, channels in declared_channels.items()
        }
    except (TypeError, ValueError) as error:
        raise ValueError(
            "CHI coherence port_channels contains an unknown channel"
        ) from error
    if not channels_by_port:
        raise ValueError(
            "CHI coherence binding requires at least one transport port"
        )
    if any(not isinstance(name, str) or not name for name in channels_by_port):
        raise ValueError(
            "CHI coherence binding port names must be non-empty strings"
        )
    unknown_ports = set(channels_by_port) - set(virtual_dut.ports)
    if unknown_ports:
        raise ValueError(
            f"CHI coherence binding references unknown ports: "
            f"{sorted(unknown_ports)!r}"
        )

    port_bindings: list[ChiParticipantPortBinding] = []
    for port_name in virtual_dut.ports:
        channels = channels_by_port.get(port_name)
        if channels is None:
            continue
        port = virtual_dut.port(port_name)
        if not isinstance(port, TransportPort):
            raise TypeError(
                f"CHI coherence port {virtual_dut.name}.{port_name} is not "
                "a TransportPort"
            )
        if port.transport_family != CHI_ISSUE_H_TRANSPORT_FAMILY:
            raise ValueError(
                f"CHI coherence port {virtual_dut.name}.{port_name} uses "
                "another transport family"
            )
        if (
            port.direction is TransportDirection.RECEIVE
            and ChiChannelKind.REQ in channels
        ):
            raise ValueError(
                "a coherent RN cannot receive REQ on its CHI transaction "
                "facet"
            )
        if (
            port.direction is TransportDirection.TRANSMIT
            and ChiChannelKind.SNP in channels
        ):
            raise ValueError(
                "a coherent RN cannot transmit SNP on its CHI transaction "
                "facet"
            )
        port_bindings.append(
            ChiParticipantPortBinding(port, channels)
        )

    participant = ChiCoherentRnNode(
        (
            f"{virtual_dut.name}.coherence"
            if participant_name is None
            else participant_name
        ),
        node_id,
        home_node_id,
        cache_core=cache_core,
        initial_permissions=initial_permissions,
        outstanding_capacity=coherence_transaction_capacity,
    )
    binding = ChiParticipantBinding(
        (
            f"{virtual_dut.name}.chi"
            if binding_name is None
            else binding_name
        ),
        virtual_dut,
        participant,
        tuple(port_bindings),
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
    return bind_chi_issue_h_cache_vdut(
        virtual_dut,
        cache_core,
        node_id,
        home_node_id,
        port_channels={
            tx.name: frozenset(
                (
                    ChiChannelKind.REQ,
                    ChiChannelKind.RSP,
                    ChiChannelKind.DAT,
                )
            ),
            rx.name: frozenset(
                (
                    ChiChannelKind.RSP,
                    ChiChannelKind.SNP,
                    ChiChannelKind.DAT,
                )
            ),
        },
        initial_permissions=initial_permissions,
        coherence_transaction_capacity=coherence_transaction_capacity,
    )


def bind_chi_issue_h_cache_lines(
    virtual_dut: VirtualDut,
    node_id: int,
    home_node_id: int,
    *,
    port_channels: Mapping[str, frozenset[ChiChannelKind]],
    initial_lines: tuple[ChiCacheLine, ...] = (),
    participant_name: str | None = None,
    binding_name: str | None = None,
    coherence_transaction_capacity: int = 4,
) -> ChiIssueHCacheVdutAssembly:
    """Build simple line storage and bind it to an existing VirtualDut.

    Use :func:`bind_chi_issue_h_cache_vdut` when the caller already owns a
    protocol-neutral :class:`CacheCore`.
    """

    if not isinstance(virtual_dut, VirtualDut):
        raise TypeError(
            "CHI cache-line binding requires an existing VirtualDut"
        )
    cache_core, permissions = _build_cache_core(
        virtual_dut.name,
        initial_lines,
    )
    return bind_chi_issue_h_cache_vdut(
        virtual_dut,
        cache_core,
        node_id,
        home_node_id,
        port_channels=port_channels,
        initial_permissions=permissions,
        participant_name=participant_name,
        binding_name=binding_name,
        coherence_transaction_capacity=coherence_transaction_capacity,
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

    cache_core, permissions = _build_cache_core(name, initial_lines)
    return attach_chi_issue_h_coherence(
        name,
        cache_core,
        node_id,
        home_node_id,
        initial_permissions=permissions,
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


def _build_cache_core(
    name: str,
    initial_lines: tuple[ChiCacheLine, ...],
) -> tuple[CacheCore[CacheLinePayload], Mapping[int, ChiCacheState]]:
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
    return (
        CacheCore(f"{name}.cache", cache_store),
        {item.address: item.state for item in lines},
    )


__all__ = [
    "ChiIssueHCacheVdutAssembly",
    "attach_chi_issue_h_coherence",
    "bind_chi_issue_h_cache_lines",
    "bind_chi_issue_h_cache_vdut",
    "build_chi_cache_participant_fixture",
    "build_chi_issue_h_cache_vdut",
]
