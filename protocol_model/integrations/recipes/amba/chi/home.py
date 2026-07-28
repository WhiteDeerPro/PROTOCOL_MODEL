"""Bind a coherent CHI Issue H Home to protocol-neutral line backing.

The backing core owns full-line payload state and its prepare/commit contract.
The CHI participant adds directory, transaction, Snoop, and completion
behavior.  This recipe binds both responsibilities to one topology-visible
``VirtualDut`` without turning the backing core into a second module identity.

The current CHI runtime executes the participant directly rather than lowering
packets through ``VirtualDutBackend.accept``.  Binding a VirtualDut that already
has an executable backend would therefore create two independently initialized
state authorities, so this first profile rejects that construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiCoherentHomeNode,
    ChiCoherentRetryAdmissionPolicy,
    ChiEvictRetryAdmissionPolicy,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
    ChiReadUniqueNderrPolicy,
    ChiWriteEvictOrEvictPolicy,
    ChiVirtualDutFacets,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.virtual_dut.backend.backing import FullLineBackingCore
from protocol_model.virtual_dut.backend.cache import (
    CacheCore,
    CacheLinePayload,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


@dataclass(frozen=True)
class ChiIssueHHomeVdutAssembly:
    """One coherent Home module, backing core, and CHI transaction facet."""

    virtual_dut: VirtualDut
    backing_core: FullLineBackingCore
    participant: ChiCoherentHomeNode
    facets: ChiVirtualDutFacets
    clean_residency_core: CacheCore[CacheLinePayload] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.virtual_dut, VirtualDut):
            raise TypeError("CHI Home assembly requires a VirtualDut")
        if not isinstance(self.backing_core, FullLineBackingCore):
            raise TypeError(
                "CHI Home assembly requires a FullLineBackingCore"
            )
        if not isinstance(self.participant, ChiCoherentHomeNode):
            raise TypeError(
                "CHI Home assembly requires a coherent Home participant"
            )
        if self.participant.backing_core is not self.backing_core:
            raise ValueError(
                "CHI Home participant must use the assembled backing core"
            )
        if (
            self.clean_residency_core is not None
            and not isinstance(self.clean_residency_core, CacheCore)
        ):
            raise TypeError(
                "CHI Home clean residency requires CacheCore or None"
            )
        if (
            self.participant.clean_residency_core
            is not self.clean_residency_core
        ):
            raise ValueError(
                "CHI Home participant must use the assembled clean "
                "residency core"
            )
        if not isinstance(self.facets, ChiVirtualDutFacets):
            raise TypeError("CHI Home assembly requires CHI behavior facets")
        if self.facets.dut is not self.virtual_dut:
            raise ValueError(
                "CHI Home facets must bind the assembled VirtualDut"
            )
        if len(self.facets.facets) != 1:
            raise ValueError(
                "the current CHI Home recipe requires one transaction facet"
            )
        facet = self.facets.facets[0]
        if facet.kind is not ChiFacetKind.TRANSACTION:
            raise ValueError(
                "the CHI Home behavior must be a transaction facet"
            )
        if facet.component is not self.participant:
            raise ValueError(
                "CHI Home facet must use the assembled participant"
            )

    @property
    def binding(self) -> ChiParticipantBinding:
        """Return the participant binding consumed by current CHI sessions."""

        return self.facets.facets[0].binding


def bind_chi_issue_h_home_vdut(
    virtual_dut: VirtualDut,
    backing_core: FullLineBackingCore,
    node_id: int,
    *,
    port_channels: Mapping[str, frozenset[ChiChannelKind]],
    initial_directory: tuple[ChiHomeDirectoryEntry, ...],
    clean_residency_core: CacheCore[CacheLinePayload] | None = None,
    participant_name: str | None = None,
    binding_name: str | None = None,
    transaction_capacity: int = 4,
    initial_snoop_transaction_id: int = 0x100,
    initial_data_buffer_id: int = 0x200,
    allow_dirty_data_transfer: bool = False,
    default_protocol_credit_type: int = 0,
    retry_policy: ChiCoherentRetryAdmissionPolicy | None = None,
    evict_retry_policy: ChiEvictRetryAdmissionPolicy | None = None,
    read_unique_nderr_policy: ChiReadUniqueNderrPolicy | None = None,
    write_evict_or_evict_policy: (
        ChiWriteEvictOrEvictPolicy | None
    ) = None,
) -> ChiIssueHHomeVdutAssembly:
    """Bind coherent Home behavior to one existing canonical VirtualDut.

    The binder creates no ports, connections, address claims, or replacement
    VirtualDut.  The caller must add this exact ``virtual_dut`` object to its
    ``SystemProtocol`` and connect the selected transport ports.

    This is the RN-facing reference-backing profile.  It receives REQ, RSP,
    and DAT; it transmits RSP, SNP, and DAT.  A future topology-visible
    HN-to-SN downstream transaction can add its own behavior boundary rather
    than treating an unsupported transmitted REQ as part of this participant.
    """

    if not isinstance(virtual_dut, VirtualDut):
        raise TypeError(
            "CHI Home binding requires an existing VirtualDut"
        )
    if virtual_dut.backend is not None:
        raise ValueError(
            "CHI Home binding requires a VirtualDut without an executable "
            "backend to avoid two reference-backing authorities"
        )
    if not isinstance(backing_core, FullLineBackingCore):
        raise TypeError(
            "CHI Home binding requires FullLineBackingCore"
        )
    try:
        declared_channels = dict(port_channels)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "CHI Home port_channels requires a port-to-channel mapping"
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
            "CHI Home port_channels contains an unknown channel"
        ) from error
    if not channels_by_port:
        raise ValueError(
            "CHI Home binding requires at least one transport port"
        )
    if any(not isinstance(name, str) or not name for name in channels_by_port):
        raise ValueError(
            "CHI Home binding port names must be non-empty strings"
        )
    unknown_ports = set(channels_by_port) - set(virtual_dut.ports)
    if unknown_ports:
        raise ValueError(
            f"CHI Home binding references unknown ports: "
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
                f"CHI Home port {virtual_dut.name}.{port_name} is not a "
                "TransportPort"
            )
        if port.transport_family != CHI_ISSUE_H_TRANSPORT_FAMILY:
            raise ValueError(
                f"CHI Home port {virtual_dut.name}.{port_name} uses another "
                "transport family"
            )
        if (
            port.direction is TransportDirection.TRANSMIT
            and ChiChannelKind.REQ in channels
        ):
            raise ValueError(
                "the current coherent Home cannot transmit REQ on its CHI "
                "transaction facet"
            )
        if (
            port.direction is TransportDirection.RECEIVE
            and ChiChannelKind.SNP in channels
        ):
            raise ValueError(
                "the current coherent Home cannot receive SNP on its CHI "
                "transaction facet"
            )
        port_bindings.append(
            ChiParticipantPortBinding(port, channels)
        )

    participant = ChiCoherentHomeNode(
        (
            f"{virtual_dut.name}.home"
            if participant_name is None
            else participant_name
        ),
        node_id,
        backing_core=backing_core,
        clean_residency_core=clean_residency_core,
        initial_directory=initial_directory,
        transaction_capacity=transaction_capacity,
        initial_snoop_transaction_id=initial_snoop_transaction_id,
        initial_data_buffer_id=initial_data_buffer_id,
        allow_dirty_data_transfer=allow_dirty_data_transfer,
        default_protocol_credit_type=default_protocol_credit_type,
        retry_policy=retry_policy,
        evict_retry_policy=evict_retry_policy,
        read_unique_nderr_policy=read_unique_nderr_policy,
        write_evict_or_evict_policy=write_evict_or_evict_policy,
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
    return ChiIssueHHomeVdutAssembly(
        virtual_dut=virtual_dut,
        backing_core=backing_core,
        participant=participant,
        facets=ChiVirtualDutFacets(virtual_dut, (facet,)),
        clean_residency_core=clean_residency_core,
    )


def attach_chi_issue_h_home(
    name: str,
    backing_core: FullLineBackingCore,
    node_id: int,
    *,
    initial_directory: tuple[ChiHomeDirectoryEntry, ...],
    clean_residency_core: CacheCore[CacheLinePayload] | None = None,
    transaction_capacity: int = 4,
    initial_snoop_transaction_id: int = 0x100,
    initial_data_buffer_id: int = 0x200,
    allow_dirty_data_transfer: bool = False,
    default_protocol_credit_type: int = 0,
    retry_policy: ChiCoherentRetryAdmissionPolicy | None = None,
    evict_retry_policy: ChiEvictRetryAdmissionPolicy | None = None,
    read_unique_nderr_policy: ChiReadUniqueNderrPolicy | None = None,
    write_evict_or_evict_policy: (
        ChiWriteEvictOrEvictPolicy | None
    ) = None,
    transmit_port_name: str = "chi_tx",
    receive_port_name: str = "chi_rx",
    clock_domain: str | None = None,
    reset_domain: str | None = None,
) -> ChiIssueHHomeVdutAssembly:
    """Create the first Home VirtualDut around an existing backing core.

    The default boundary declares the channel superset used by the implemented
    coherent-read, CleanUnique, dirty-writeback, and clean
    WriteEvictFull/residency slices:

    - transmit: RSP, SNP, and DAT;
    - receive: REQ, RSP, and DAT.

    Feature and flow closure still decides which of these channels a selected
    lifecycle must make reachable.
    """

    if not isinstance(backing_core, FullLineBackingCore):
        raise TypeError(
            "CHI Home attachment requires FullLineBackingCore"
        )
    if transmit_port_name == receive_port_name:
        raise ValueError(
            "CHI Home attachment requires distinct transmit and receive "
            "port names"
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
        behavior_tags=frozenset(
            (
                DutBehaviorTag.ADDRESSABLE,
                DutBehaviorTag.INITIATING,
            )
        ),
        description=(
            "CHI Issue H coherent Home with protocol-neutral line backing"
        ),
    )
    return bind_chi_issue_h_home_vdut(
        virtual_dut,
        backing_core,
        node_id,
        port_channels={
            tx.name: frozenset(
                (
                    ChiChannelKind.RSP,
                    ChiChannelKind.SNP,
                    ChiChannelKind.DAT,
                )
            ),
            rx.name: frozenset(
                (
                    ChiChannelKind.REQ,
                    ChiChannelKind.RSP,
                    ChiChannelKind.DAT,
                )
            ),
        },
        initial_directory=initial_directory,
        clean_residency_core=clean_residency_core,
        transaction_capacity=transaction_capacity,
        initial_snoop_transaction_id=initial_snoop_transaction_id,
        initial_data_buffer_id=initial_data_buffer_id,
        allow_dirty_data_transfer=allow_dirty_data_transfer,
        default_protocol_credit_type=default_protocol_credit_type,
        retry_policy=retry_policy,
        evict_retry_policy=evict_retry_policy,
        read_unique_nderr_policy=read_unique_nderr_policy,
        write_evict_or_evict_policy=write_evict_or_evict_policy,
    )


__all__ = [
    "ChiIssueHHomeVdutAssembly",
    "attach_chi_issue_h_home",
    "bind_chi_issue_h_home_vdut",
]
