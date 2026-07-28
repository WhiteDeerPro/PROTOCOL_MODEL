"""Executable CHI Issue H coherence stories for the flow gallery.

The cases in this module are deliberately small direct topologies.  They run
the production coherence participants and transport scheduler; the returned
events are therefore observations of the model, not a hand-authored message
sequence for a diagram.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.participants.capability import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
    CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
    CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCleanUniqueMessage,
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiCompMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiMakeUniqueMessage,
    ChiReadUniqueMessage,
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpRespDataMessage,
    ChiSnpRespMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_MAKE_UNIQUE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
    CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEvent,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceNetworkState,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCleanUnique,
    ChiSubmitCoherentRead,
    ChiSubmitMakeUnique,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiSnpChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import SemanticRun, Verdict
from protocol_model.system import (
    AddressClaim,
    AddressWindow,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend import BackingLine, FullLineBackingCore
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


REQUESTER = 0x07
FIRST_PEER = 0x08
SECOND_PEER = 0x09
HOME = 0x21
ADDRESS = 0x8000
CLEAN_DATA = (1 << 400) | 0xC0DE
DIRTY_DATA = (1 << 420) | 0xD177
LOCAL_WRITE_DATA = (1 << 500) | 0x4E57


@dataclass(frozen=True)
class FlowCaseRun:
    """One executed case plus stable inputs for later visual projection."""

    case_id: str
    title: str
    session: ChiCoherenceNetworkSession
    initial_state: ChiCoherenceNetworkState
    final_state: ChiCoherenceNetworkState
    verdict: Verdict
    assertions: Mapping[str, bool]
    emissions: tuple[ChiCoherenceNetworkEvent, ...]
    state_history: tuple[ChiCoherenceNetworkState, ...]
    run: SemanticRun

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assertions",
            MappingProxyType(dict(self.assertions)),
        )

    @property
    def initial_coherence(self):
        return self.initial_state.coherence

    @property
    def final_coherence(self):
        return self.final_state.coherence

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS and all(self.assertions.values())


@dataclass(frozen=True)
class _Peer:
    dut_name: str
    node_id: int
    state: ChiCacheState
    data: int | None


@dataclass(frozen=True)
class _DirectCase:
    name: str
    requester_state: ChiCacheState
    requester_data: int | None
    peers: tuple[_Peer, ...]
    directory_sharers: frozenset[int]
    shared_dirty_owner: int | None
    backing_data: int
    completion_channel: ChiChannelKind
    peer_return_channels: frozenset[ChiChannelKind]
    required_feature: object
    requester_capabilities: frozenset
    home_capabilities: frozenset
    snoopee_capabilities: frozenset
    system_capabilities: frozenset
    allow_dirty_data_transfer: bool = False


def _port(name: str, direction: TransportDirection) -> TransportPort:
    return TransportPort(
        name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        direction,
        clock_domain="chi_clk",
    )


def _link_profile(
    name: str,
    channels: frozenset[ChiChannelKind],
) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=(
            ChiReqChannelProfile(ChiIssueHReqProfile(), (1,), f"{name}.req")
            if ChiChannelKind.REQ in channels
            else None
        ),
        response=(
            ChiRspChannelProfile(ChiIssueHRspProfile(), 1, f"{name}.rsp")
            if ChiChannelKind.RSP in channels
            else None
        ),
        snoop=(
            ChiSnpChannelProfile(ChiIssueHSnpProfile(), 1, f"{name}.snp")
            if ChiChannelKind.SNP in channels
            else None
        ),
        data=(
            ChiDatChannelProfile(
                ChiIssueHDatProfile(data_width=512),
                1,
                f"{name}.dat",
            )
            if ChiChannelKind.DAT in channels
            else None
        ),
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _build_direct_session(case: _DirectCase) -> ChiCoherenceNetworkSession:
    builder = SystemProtocolBuilder(case.name)
    builder.add_dut(
        VirtualDut(
            "rn0",
            {
                "tx_request_ack": _port(
                    "tx_request_ack",
                    TransportDirection.TRANSMIT,
                ),
                "rx_completion": _port(
                    "rx_completion",
                    TransportDirection.RECEIVE,
                ),
            },
        )
    )
    for peer in case.peers:
        builder.add_dut(
            VirtualDut(
                peer.dut_name,
                {
                    "rx_snoop": _port(
                        "rx_snoop",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_snoop_result": _port(
                        "tx_snoop_result",
                        TransportDirection.TRANSMIT,
                    ),
                },
            )
        )
    builder.add_dut(
        VirtualDut(
            "hn0",
            {
                "rx_request_ack": _port(
                    "rx_request_ack",
                    TransportDirection.RECEIVE,
                ),
                "tx_completion": _port(
                    "tx_completion",
                    TransportDirection.TRANSMIT,
                ),
                **{
                    f"tx_snoop_{peer.dut_name}": _port(
                        f"tx_snoop_{peer.dut_name}",
                        TransportDirection.TRANSMIT,
                    )
                    for peer in case.peers
                },
                **{
                    f"rx_result_{peer.dut_name}": _port(
                        f"rx_result_{peer.dut_name}",
                        TransportDirection.RECEIVE,
                    )
                    for peer in case.peers
                },
            },
        )
    )

    connection_specs = [
        (
            "request_ack",
            VirtualDutPortRef("rn0", "tx_request_ack"),
            VirtualDutPortRef("hn0", "rx_request_ack"),
            frozenset((ChiChannelKind.REQ, ChiChannelKind.RSP)),
        ),
        (
            "completion",
            VirtualDutPortRef("hn0", "tx_completion"),
            VirtualDutPortRef("rn0", "rx_completion"),
            frozenset((case.completion_channel,)),
        ),
    ]
    for peer in case.peers:
        connection_specs.extend(
            (
                (
                    f"snoop_{peer.dut_name}",
                    VirtualDutPortRef(
                        "hn0",
                        f"tx_snoop_{peer.dut_name}",
                    ),
                    VirtualDutPortRef(peer.dut_name, "rx_snoop"),
                    frozenset((ChiChannelKind.SNP,)),
                ),
                (
                    f"result_{peer.dut_name}",
                    VirtualDutPortRef(
                        peer.dut_name,
                        "tx_snoop_result",
                    ),
                    VirtualDutPortRef(
                        "hn0",
                        f"rx_result_{peer.dut_name}",
                    ),
                    case.peer_return_channels,
                ),
            )
        )
    for name, transmitter, receiver, channels in connection_specs:
        builder.connect_transport(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            transmitter,
            receiver,
            profile=_link_profile(name, channels),
        )

    claim_name = "hn0.cache_line"
    builder.add_address_claim(
        AddressClaim(
            claim_name,
            VirtualDutPortRef("hn0", "rx_request_ack"),
            AddressWindow(ADDRESS, 0x40),
        )
    )
    system = builder.build().elaborate()
    duts = system.spec.virtual_duts

    requester = bind_chi_issue_h_cache_lines(
        duts["rn0"],
        REQUESTER,
        HOME,
        port_channels={
            "tx_request_ack": frozenset(
                (ChiChannelKind.REQ, ChiChannelKind.RSP)
            ),
            "rx_completion": frozenset((case.completion_channel,)),
        },
        initial_lines=(
            ChiCacheLine(
                ADDRESS,
                case.requester_state,
                case.requester_data,
            ),
        ),
        participant_name="requester",
        binding_name="rn0",
    )
    peer_assemblies = {
        peer.dut_name: bind_chi_issue_h_cache_lines(
            duts[peer.dut_name],
            peer.node_id,
            HOME,
            port_channels={
                "rx_snoop": frozenset((ChiChannelKind.SNP,)),
                "tx_snoop_result": case.peer_return_channels,
            },
            initial_lines=(
                ChiCacheLine(ADDRESS, peer.state, peer.data),
            ),
            participant_name=f"snoopee_{peer.node_id:02x}",
            binding_name=peer.dut_name,
        )
        for peer in case.peers
    }
    home = ChiCoherentHomeNode(
        "home",
        HOME,
        backing_core=FullLineBackingCore(
            "home.backing",
            line_bytes=64,
            initial_lines=(BackingLine(ADDRESS, case.backing_data),),
        ),
        initial_directory=(
            ChiHomeDirectoryEntry(
                ADDRESS,
                sharers=case.directory_sharers,
                shared_dirty_owner=case.shared_dirty_owner,
            ),
        ),
        initial_snoop_transaction_id=0x100,
        initial_data_buffer_id=0x200,
        allow_dirty_data_transfer=case.allow_dirty_data_transfer,
    )
    port_binding = ChiParticipantPortBinding
    home_binding = ChiParticipantBinding(
        "hn0",
        duts["hn0"],
        home,
        (
            port_binding(
                duts["hn0"].port("rx_request_ack"),
                frozenset((ChiChannelKind.REQ, ChiChannelKind.RSP)),
            ),
            port_binding(
                duts["hn0"].port("tx_completion"),
                frozenset((case.completion_channel,)),
            ),
            *(
                binding
                for peer in case.peers
                for binding in (
                    port_binding(
                        duts["hn0"].port(
                            f"tx_snoop_{peer.dut_name}"
                        ),
                        frozenset((ChiChannelKind.SNP,)),
                    ),
                    port_binding(
                        duts["hn0"].port(
                            f"rx_result_{peer.dut_name}"
                        ),
                        case.peer_return_channels,
                    ),
                )
            ),
        ),
        frozenset((HOME,)),
    )

    resolved = resolve_chi_system(
        system,
        facets=(
            requester.facets.facets[0],
            *(
                peer_assemblies[peer.dut_name].facets.facets[0]
                for peer in case.peers
            ),
            ChiBehaviorFacet.from_binding(
                home_binding,
                ChiFacetKind.TRANSACTION,
            ),
        ),
        feature_contract=ChiFeatureContract(
            {"requester": "rn0"},
            frozenset((case.required_feature,)),
        ),
        authority_contract=ChiCoherenceAuthorityContract(
            authorities=(
                ChiHomeAuthority(
                    claim_name,
                    "hn0",
                    "coherent_agents",
                ),
            ),
            domains=(
                ChiCoherenceDomain(
                    "coherent_agents",
                    frozenset(
                        ("rn0", *(peer.dut_name for peer in case.peers))
                    ),
                ),
            ),
        ),
        feature_address_claim=claim_name,
        participant_capabilities=(
            ChiParticipantCapability(
                "rn0",
                case.requester_capabilities,
            ),
            ChiParticipantCapability("hn0", case.home_capabilities),
            *(
                ChiParticipantCapability(
                    peer.dut_name,
                    case.snoopee_capabilities,
                )
                for peer in case.peers
            ),
        ),
        system_capabilities=case.system_capabilities,
    )
    return ChiCoherenceNetworkSession.from_resolved(resolved)


def _execute(session, action) -> tuple:
    initial = session.initial_state()
    issued = session.step(initial, action)
    if issued.fault is not None:
        raise RuntimeError(
            f"{session.name} submit faulted: {issued.fault.reason}"
        )
    if issued.blocked is not None:
        raise RuntimeError(
            f"{session.name} submit blocked: {issued.blocked.reason}"
        )
    scheduled = session.run_until_quiescent(
        issued.state,
        max_steps=1024,
    )
    combined = SemanticRun(
        scheduled.verdict,
        scheduled.final_state,
        issued.emissions + scheduled.emissions,
        scheduled.violations,
        (initial, *scheduled.state_history),
        scheduled.blocked,
    )
    return initial, combined


def _endpoint_events(run: SemanticRun) -> tuple[ChiCoherenceNetworkEvent, ...]:
    return tuple(
        event
        for event in run.emissions
        if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
    )


def _line(state: ChiCoherenceNetworkState, node_id: int):
    return state.coherence.request_nodes[node_id].line_at(ADDRESS)


def _result(
    case_id: str,
    title: str,
    session: ChiCoherenceNetworkSession,
    initial: ChiCoherenceNetworkState,
    run: SemanticRun,
    assertions: Mapping[str, bool],
) -> FlowCaseRun:
    return FlowCaseRun(
        case_id=case_id,
        title=title,
        session=session,
        initial_state=initial,
        final_state=run.final_state,
        verdict=run.verdict,
        assertions=assertions,
        emissions=run.emissions,
        state_history=run.state_history,
        run=run,
    )


def run_clean_read_unique_fanout() -> FlowCaseRun:
    """ReadUnique invalidates two clean sharers and joins their responses."""

    peers = (
        _Peer("rn1", FIRST_PEER, ChiCacheState.SC, CLEAN_DATA),
        _Peer("rn2", SECOND_PEER, ChiCacheState.SC, CLEAN_DATA),
    )
    session = _build_direct_session(
        _DirectCase(
            name="showcase_clean_read_unique_fanout",
            requester_state=ChiCacheState.I,
            requester_data=None,
            peers=peers,
            directory_sharers=frozenset(
                (FIRST_PEER, SECOND_PEER)
            ),
            shared_dirty_owner=None,
            backing_data=CLEAN_DATA,
            completion_channel=ChiChannelKind.DAT,
            peer_return_channels=frozenset((ChiChannelKind.RSP,)),
            required_feature=CHI_FEATURE_CLEAN_READ_UNIQUE,
            requester_capabilities=(
                CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
            ),
            home_capabilities=CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
            snoopee_capabilities=(
                CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
            ),
        )
    )
    initial, run = _execute(
        session,
        ChiSubmitCoherentRead(
            REQUESTER,
            ChiReadUniqueMessage(0x12, ADDRESS),
        ),
    )
    endpoint = _endpoint_events(run)
    counts = Counter(type(event.packet.message) for event in endpoint)
    snoop_targets = {
        event.packet.target_id
        for event in endpoint
        if isinstance(event.packet.message, ChiSnpUniqueMessage)
    }
    response_indices = [
        index
        for index, event in enumerate(endpoint)
        if isinstance(event.packet.message, ChiSnpRespMessage)
    ]
    completion_indices = [
        index
        for index, event in enumerate(endpoint)
        if isinstance(event.packet.message, ChiCompDataMessage)
    ]
    final = run.final_state
    requester_line = _line(final, REQUESTER)
    peer_lines = tuple(_line(final, peer.node_id) for peer in peers)
    directory = final.coherence.home.directory[ADDRESS]
    assertions = {
        "scheduler_passed": run.verdict is Verdict.PASS,
        "quiescent": session.is_quiescent(final),
        "seven_packets_reached_endpoints": len(endpoint) == 7,
        "two_snp_unique_packets_fanned_out": (
            counts[ChiSnpUniqueMessage] == 2
            and snoop_targets == {FIRST_PEER, SECOND_PEER}
        ),
        "two_clean_snoop_responses_joined": (
            counts[ChiSnpRespMessage] == 2
            and len(response_indices) == 2
            and len(completion_indices) == 1
            and max(response_indices) < completion_indices[0]
        ),
        "one_comp_data_and_ack_completed": (
            counts[ChiCompDataMessage] == 1
            and counts[ChiCompAckMessage] == 1
        ),
        "requester_became_unique_clean": (
            requester_line is not None
            and requester_line.state is ChiCacheState.UC
            and requester_line.data == CLEAN_DATA
        ),
        "clean_peers_were_invalidated": all(
            line is not None
            and line.state is ChiCacheState.I
            and line.data is None
            for line in peer_lines
        ),
        "directory_committed_unique_owner": (
            directory.unique_owner == REQUESTER
            and not directory.sharers
            and directory.shared_dirty_owner is None
        ),
    }
    return _result(
        "clean-read-unique-fanout",
        "Clean ReadUnique: two-peer fanout and response join",
        session,
        initial,
        run,
        assertions,
    )


def run_dirty_peer_clean_unique() -> FlowCaseRun:
    """CleanUnique absorbs shared-dirty peer data through DAT."""

    peer = _Peer("rn1", FIRST_PEER, ChiCacheState.SD, DIRTY_DATA)
    session = _build_direct_session(
        _DirectCase(
            name="showcase_dirty_peer_clean_unique",
            requester_state=ChiCacheState.SC,
            requester_data=DIRTY_DATA,
            peers=(peer,),
            directory_sharers=frozenset((REQUESTER, FIRST_PEER)),
            shared_dirty_owner=FIRST_PEER,
            backing_data=CLEAN_DATA,
            completion_channel=ChiChannelKind.RSP,
            peer_return_channels=frozenset(
                (ChiChannelKind.RSP, ChiChannelKind.DAT)
            ),
            required_feature=(
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            ),
            requester_capabilities=(
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES
            ),
            home_capabilities=(
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
                | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES
            ),
            snoopee_capabilities=(
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
                | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES
            ),
            system_capabilities=frozenset(
                (
                    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
                    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
                )
            ),
            allow_dirty_data_transfer=True,
        )
    )
    initial, run = _execute(
        session,
        ChiSubmitCleanUnique(
            REQUESTER,
            ChiCleanUniqueMessage(0x31, ADDRESS),
        ),
    )
    endpoint = _endpoint_events(run)
    counts = Counter(type(event.packet.message) for event in endpoint)
    final = run.final_state
    requester_line = _line(final, REQUESTER)
    peer_line = _line(final, FIRST_PEER)
    initial_backing = initial.coherence.home.backing.line_at(ADDRESS)
    final_backing = final.coherence.home.backing.line_at(ADDRESS)
    directory = final.coherence.home.directory[ADDRESS]
    assertions = {
        "scheduler_passed": run.verdict is Verdict.PASS,
        "quiescent": session.is_quiescent(final),
        "dirty_snoop_used_dat": (
            counts[ChiSnpRespDataMessage] == 1
            and any(
                event.packet.channel is ChiChannelKind.DAT
                for event in endpoint
            )
        ),
        "clean_unique_lifecycle_completed": (
            counts[ChiCleanUniqueMessage] == 1
            and counts[ChiSnpCleanInvalidMessage] == 1
            and counts[ChiCompMessage] == 1
            and counts[ChiCompAckMessage] == 1
        ),
        "home_absorbed_dirty_data": (
            initial_backing is not None
            and initial_backing.data == CLEAN_DATA
            and final_backing is not None
            and final_backing.data == DIRTY_DATA
            and final_backing.version > initial_backing.version
        ),
        "requester_became_unique_clean": (
            requester_line is not None
            and requester_line.state is ChiCacheState.UC
            and requester_line.data == DIRTY_DATA
        ),
        "dirty_peer_was_invalidated": (
            peer_line is not None
            and peer_line.state is ChiCacheState.I
            and peer_line.data is None
        ),
        "directory_committed_unique_owner": (
            directory.unique_owner == REQUESTER
            and not directory.sharers
            and directory.shared_dirty_owner is None
        ),
    }
    return _result(
        "dirty-peer-clean-unique",
        "CleanUnique: absorb a shared-dirty peer through DAT",
        session,
        initial,
        run,
        assertions,
    )


def run_make_unique_local_intent() -> FlowCaseRun:
    """MakeUnique obtains permission without carrying the local write on DAT."""

    peer = _Peer("rn1", FIRST_PEER, ChiCacheState.SD, CLEAN_DATA)
    session = _build_direct_session(
        _DirectCase(
            name="showcase_make_unique_local_intent",
            requester_state=ChiCacheState.I,
            requester_data=None,
            peers=(peer,),
            directory_sharers=frozenset((FIRST_PEER,)),
            shared_dirty_owner=FIRST_PEER,
            backing_data=CLEAN_DATA,
            completion_channel=ChiChannelKind.RSP,
            peer_return_channels=frozenset((ChiChannelKind.RSP,)),
            required_feature=CHI_FEATURE_MAKE_UNIQUE,
            requester_capabilities=CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
            home_capabilities=CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
            snoopee_capabilities=CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
            system_capabilities=frozenset(
                (CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE,)
            ),
        )
    )
    initial, run = _execute(
        session,
        ChiSubmitMakeUnique(
            REQUESTER,
            ChiMakeUniqueMessage(0x41, ADDRESS),
            LOCAL_WRITE_DATA,
        ),
    )
    endpoint = _endpoint_events(run)
    counts = Counter(type(event.packet.message) for event in endpoint)
    final = run.final_state
    requester_line = _line(final, REQUESTER)
    peer_line = _line(final, FIRST_PEER)
    initial_backing = initial.coherence.home.backing.line_at(ADDRESS)
    final_backing = final.coherence.home.backing.line_at(ADDRESS)
    directory = final.coherence.home.directory[ADDRESS]
    assertions = {
        "scheduler_passed": run.verdict is Verdict.PASS,
        "quiescent": session.is_quiescent(final),
        "dataless_network_lifecycle": (
            all(
                event.packet.channel is not ChiChannelKind.DAT
                for event in endpoint
            )
            and ChiChannelKind.DAT
            not in {
                channel
                for _source, _target, channel
                in session.route_by_packet_key
            }
        ),
        "make_unique_lifecycle_completed": (
            counts[ChiMakeUniqueMessage] == 1
            and counts[ChiSnpMakeInvalidMessage] == 1
            and counts[ChiSnpRespMessage] == 1
            and counts[ChiCompMessage] == 1
            and counts[ChiCompAckMessage] == 1
        ),
        "local_full_line_intent_installed_dirty_unique": (
            LOCAL_WRITE_DATA.bit_length() <= 512
            and requester_line is not None
            and requester_line.state is ChiCacheState.UD
            and requester_line.data == LOCAL_WRITE_DATA
        ),
        "dirty_peer_was_invalidated_without_dat": (
            peer_line is not None
            and peer_line.state is ChiCacheState.I
            and peer_line.data is None
        ),
        "backing_copy_was_not_rewritten": (
            initial_backing is not None
            and final_backing is not None
            and final_backing.data == initial_backing.data == CLEAN_DATA
            and final_backing.version == initial_backing.version
        ),
        "directory_committed_unique_owner": (
            directory.unique_owner == REQUESTER
            and not directory.sharers
            and directory.shared_dirty_owner is None
        ),
    }
    return _result(
        "make-unique-local-intent",
        "MakeUnique: dataless permission and local full-line intent",
        session,
        initial,
        run,
        assertions,
    )


def run_coherence_cases() -> Mapping[str, FlowCaseRun]:
    """Run the three selected coherence cases in deterministic gallery order."""

    cases = (
        run_clean_read_unique_fanout(),
        run_dirty_peer_clean_unique(),
        run_make_unique_local_intent(),
    )
    return MappingProxyType({case.case_id: case for case in cases})


__all__ = [
    "ADDRESS",
    "CLEAN_DATA",
    "DIRTY_DATA",
    "FIRST_PEER",
    "FlowCaseRun",
    "HOME",
    "LOCAL_WRITE_DATA",
    "REQUESTER",
    "SECOND_PEER",
    "run_clean_read_unique_fanout",
    "run_coherence_cases",
    "run_dirty_peer_clean_unique",
    "run_make_unique_local_intent",
]
