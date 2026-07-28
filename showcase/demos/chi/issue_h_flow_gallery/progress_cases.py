"""Executable CHI progress and interference cases for the flow gallery.

Both cases use a resolved RN-XP-HN topology.  Clean Evict uses the automatic
coherence-network scheduler.  Dirty WriteBackFull uses public selective
scheduler moves to hold one REQ before XP capture while a second requester
completes CleanUnique.  Every retained packet, hop, and participant state
transition is emitted by the production model; the controlled ordering is
not a network-latency claim.
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
    CHI_CLEAN_EVICT_HOME_CAPABILITIES,
    CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
    CHI_REQUEST_RETRY_HOME_CAPABILITIES,
    CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiHomeCopyBackAdmission,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiRnCopyBackOutcome,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCleanUniqueMessage,
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiEvictMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiPCrdGrantMessage,
    ChiRespCode,
    ChiRetryAckMessage,
    ChiSnpCleanInvalidMessage,
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
    ChiSnpUniqueMessage,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_EVICT_RETRY,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,
    CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
    CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
    ChiAdvanceCoherenceNetwork,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceInvariantMonitor,
    ChiCoherenceNetworkEvent,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCleanUnique,
    ChiSubmitEvict,
    ChiSubmitWriteBackFull,
    ResolvedChiSystem,
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
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


REQUESTER_NODE_ID = 0x07
CONTENDER_NODE_ID = 0x08
HOME_NODE_ID = 0x21
LINE_ADDRESS = 0x8000
STALE_BACKING_DATA = 0x1122
DIRTY_LINE_DATA = (1 << 400) | 0xD177
CLEAN_LINE_DATA = (1 << 400) | 0xE71C7
EVICT_TXN_ID = 0x31
CLEAN_UNIQUE_TXN_ID = 0x32
PROTOCOL_CREDIT_TYPE = 5


@dataclass(frozen=True)
class FlowCaseRun:
    """One executed gallery case plus evidence retained for projections."""

    case_id: str
    title: str
    session: object
    initial_state: object
    final_state: object
    verdict: Verdict
    assertions: Mapping[str, bool]
    emissions: tuple[object, ...]
    state_history: tuple[object, ...]
    run: SemanticRun[object, object, object]

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("flow-gallery case_id must be non-empty")
        if not self.title:
            raise ValueError("flow-gallery title must be non-empty")
        object.__setattr__(
            self,
            "assertions",
            MappingProxyType(dict(self.assertions)),
        )
        object.__setattr__(self, "emissions", tuple(self.emissions))
        object.__setattr__(
            self,
            "state_history",
            tuple(self.state_history),
        )

    @property
    def passed(self) -> bool:
        """Whether execution and every case-specific check passed."""

        return self.verdict is Verdict.PASS and all(
            self.assertions.values()
        )

    @property
    def initial_coherence(self):
        """Return the participant state under either supported runtime."""

        return getattr(self.initial_state, "coherence", self.initial_state)

    @property
    def final_coherence(self):
        """Return the participant state under either supported runtime."""

        return getattr(self.final_state, "coherence", self.final_state)


def _port(
    name: str,
    direction: TransportDirection,
) -> TransportPort:
    return TransportPort(
        name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        direction,
        clock_domain="chi_clk",
    )


def _link_profile(
    name: str,
    channels: ChiChannelKind | frozenset[ChiChannelKind],
) -> ChiTransportLinkProfile:
    channel_set = (
        frozenset((channels,))
        if isinstance(channels, ChiChannelKind)
        else frozenset(channels)
    )
    return ChiTransportLinkProfile(
        request=(
            ChiReqChannelProfile(
                ChiIssueHReqProfile(),
                (1,),
                f"{name}.req",
            )
            if ChiChannelKind.REQ in channel_set
            else None
        ),
        response=(
            ChiRspChannelProfile(
                ChiIssueHRspProfile(),
                1,
                f"{name}.rsp",
            )
            if ChiChannelKind.RSP in channel_set
            else None
        ),
        snoop=(
            ChiSnpChannelProfile(
                ChiIssueHSnpProfile(),
                1,
                f"{name}.snp",
            )
            if ChiChannelKind.SNP in channel_set
            else None
        ),
        data=(
            ChiDatChannelProfile(
                ChiIssueHDatProfile(data_width=512),
                1,
                f"{name}.dat",
            )
            if ChiChannelKind.DAT in channel_set
            else None
        ),
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _evict_retry_home() -> ChiCoherentHomeNode:
    return ChiCoherentHomeNode(
        "evict_retry_home",
        HOME_NODE_ID,
        backing_core=FullLineBackingCore(
            "evict_retry_home.backing",
            line_bytes=64,
            initial_lines=(
                BackingLine(LINE_ADDRESS, CLEAN_LINE_DATA),
            ),
        ),
        initial_directory=(
            ChiHomeDirectoryEntry(
                LINE_ADDRESS,
                unique_owner=REQUESTER_NODE_ID,
            ),
        ),
        transaction_capacity=1,
        evict_retry_policy=lambda request, _state: (
            PROTOCOL_CREDIT_TYPE
            if request.transaction_id == EVICT_TXN_ID
            else None
        ),
        default_protocol_credit_type=PROTOCOL_CREDIT_TYPE,
    )


def _build_evict_retry_system() -> ResolvedChiSystem:
    builder = SystemProtocolBuilder("showcase_chi_clean_evict_retry")
    builder.add_dut(
        VirtualDut(
            "rn0",
            {
                "tx_req": _port(
                    "tx_req",
                    TransportDirection.TRANSMIT,
                ),
                "rx_rsp": _port(
                    "rx_rsp",
                    TransportDirection.RECEIVE,
                ),
            },
        )
    )
    builder.add_dut(
        VirtualDut(
            "hn0",
            {
                "rx_req": _port(
                    "rx_req",
                    TransportDirection.RECEIVE,
                ),
                "tx_rsp": _port(
                    "tx_rsp",
                    TransportDirection.TRANSMIT,
                ),
            },
        )
    )
    builder.add_dut(
        VirtualDut(
            "xp0",
            {
                "from_rn0": _port(
                    "from_rn0",
                    TransportDirection.RECEIVE,
                ),
                "to_hn0": _port(
                    "to_hn0",
                    TransportDirection.TRANSMIT,
                ),
                "from_hn0": _port(
                    "from_hn0",
                    TransportDirection.RECEIVE,
                ),
                "to_rn0": _port(
                    "to_rn0",
                    TransportDirection.TRANSMIT,
                ),
            },
            behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        )
    )
    builder.connect_transport(
        "rn0_to_xp_req",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("rn0", "tx_req"),
        VirtualDutPortRef("xp0", "from_rn0"),
        profile=_link_profile(
            "rn0_to_xp_req",
            ChiChannelKind.REQ,
        ),
    )
    builder.connect_transport(
        "xp_to_hn0_req",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("xp0", "to_hn0"),
        VirtualDutPortRef("hn0", "rx_req"),
        profile=_link_profile(
            "xp_to_hn0_req",
            ChiChannelKind.REQ,
        ),
    )
    builder.connect_transport(
        "hn0_to_xp_rsp",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("hn0", "tx_rsp"),
        VirtualDutPortRef("xp0", "from_hn0"),
        profile=_link_profile(
            "hn0_to_xp_rsp",
            ChiChannelKind.RSP,
        ),
    )
    builder.connect_transport(
        "xp_to_rn0_rsp",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("xp0", "to_rn0"),
        VirtualDutPortRef("rn0", "rx_rsp"),
        profile=_link_profile(
            "xp_to_rn0_rsp",
            ChiChannelKind.RSP,
        ),
    )
    claim_name = "hn0.cache_line"
    builder.add_address_claim(
        AddressClaim(
            claim_name,
            VirtualDutPortRef("hn0", "rx_req"),
            AddressWindow(LINE_ADDRESS, 0x40),
        )
    )
    elaborated = builder.build().elaborate()
    duts = elaborated.spec.virtual_duts

    requester = bind_chi_issue_h_cache_lines(
        duts["rn0"],
        REQUESTER_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "tx_req": frozenset((ChiChannelKind.REQ,)),
            "rx_rsp": frozenset((ChiChannelKind.RSP,)),
        },
        initial_lines=(
            ChiCacheLine(
                LINE_ADDRESS,
                ChiCacheState.UC,
                CLEAN_LINE_DATA,
            ),
        ),
        participant_name="evicting_requester",
        binding_name="rn0",
    )
    home_binding = ChiParticipantBinding(
        "hn0",
        duts["hn0"],
        _evict_retry_home(),
        (
            ChiParticipantPortBinding(
                duts["hn0"].port("rx_req"),
                frozenset((ChiChannelKind.REQ,)),
            ),
            ChiParticipantPortBinding(
                duts["hn0"].port("tx_rsp"),
                frozenset((ChiChannelKind.RSP,)),
            ),
        ),
        frozenset((HOME_NODE_ID,)),
    )
    router = ChiStoreForwardRouterNode(
        "xp0",
        ingress_ports=("from_rn0", "from_hn0"),
        egress_ports=("to_hn0", "to_rn0"),
        routes=(
            ChiExactNodeRoute(
                HOME_NODE_ID,
                "to_hn0",
                frozenset((ChiChannelKind.REQ,)),
            ),
            ChiExactNodeRoute(
                REQUESTER_NODE_ID,
                "to_rn0",
                frozenset((ChiChannelKind.RSP,)),
            ),
        ),
        queue_capacity=1,
    )
    router_binding = ChiParticipantBinding(
        "xp0",
        duts["xp0"],
        router,
        (
            ChiParticipantPortBinding(
                duts["xp0"].port("from_rn0"),
                frozenset((ChiChannelKind.REQ,)),
            ),
            ChiParticipantPortBinding(
                duts["xp0"].port("to_hn0"),
                frozenset((ChiChannelKind.REQ,)),
            ),
            ChiParticipantPortBinding(
                duts["xp0"].port("from_hn0"),
                frozenset((ChiChannelKind.RSP,)),
            ),
            ChiParticipantPortBinding(
                duts["xp0"].port("to_rn0"),
                frozenset((ChiChannelKind.RSP,)),
            ),
        ),
    )
    return resolve_chi_system(
        elaborated,
        facets=(
            requester.facets.facets[0],
            ChiBehaviorFacet.from_binding(
                home_binding,
                ChiFacetKind.TRANSACTION,
            ),
            ChiBehaviorFacet.from_binding(
                router_binding,
                ChiFacetKind.FORWARDING,
            ),
        ),
        feature_contract=ChiFeatureContract(
            {"requester": "rn0"},
            frozenset((CHI_FEATURE_CLEAN_EVICT_RETRY,)),
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
                    frozenset(("rn0",)),
                ),
            ),
        ),
        feature_address_claim=claim_name,
        participant_capabilities=(
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES
                | CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_EVICT_HOME_CAPABILITIES
                | CHI_REQUEST_RETRY_HOME_CAPABILITIES,
            ),
        ),
        system_capabilities=frozenset(
            (
                CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,
                CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE,
            )
        ),
    )


def _merge_submit_and_scheduler(
    initial_state: object,
    submitted,
    scheduler_run: SemanticRun,
) -> SemanticRun[object, object, object]:
    return SemanticRun(
        scheduler_run.verdict,
        scheduler_run.final_state,
        (*submitted.emissions, *scheduler_run.emissions),
        violations=scheduler_run.violations,
        state_history=(
            initial_state,
            *scheduler_run.state_history,
        ),
        blocked=scheduler_run.blocked,
    )


def run_clean_evict_retry() -> FlowCaseRun:
    """Run Evict -> RetryAck -> P-Credit -> reissue -> Comp."""

    resolved = _build_evict_retry_system()
    session = ChiCoherenceNetworkSession.from_resolved(resolved)
    initial = session.initial_state()
    submitted = session.step(
        initial,
        ChiSubmitEvict(
            REQUESTER_NODE_ID,
            ChiEvictMessage(EVICT_TXN_ID, LINE_ADDRESS),
        ),
    )
    if submitted.fault is not None or submitted.blocked is not None:
        raise RuntimeError("clean-Evict submission was not accepted")
    scheduler_run = session.run_until_quiescent(
        submitted.state,
        max_steps=256,
    )
    run = _merge_submit_and_scheduler(
        initial,
        submitted,
        scheduler_run,
    )
    endpoint_packets = tuple(
        event.packet
        for event in run.emissions
        if (
            isinstance(event, ChiCoherenceNetworkEvent)
            and event.kind
            is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
            and event.packet is not None
        )
    )
    packet_types = tuple(
        type(packet.message) for packet in endpoint_packets
    )
    credited_request = (
        endpoint_packets[3].message
        if len(endpoint_packets) > 3
        else None
    )
    final = scheduler_run.final_state.coherence
    initial_coherence = initial.coherence
    final_line = final.request_nodes[REQUESTER_NODE_ID].line_at(
        LINE_ADDRESS
    )
    router_state = scheduler_run.final_state.network.routers["xp0"]
    assertions = {
        "resolved_topology_closed": resolved.is_closed,
        "one_explicit_xp_forwarder": (
            tuple(
                binding.name
                for binding in resolved.forwarding_bindings
            )
            == ("xp0",)
        ),
        "all_feature_flows_cross_xp_in_two_hops": all(
            len(route) == 2
            and session.network.hops[route[0]].receiver.dut == "xp0"
            and session.network.hops[route[1]].transmitter.dut == "xp0"
            for route in session.route_by_packet_key.values()
        ),
        "xp_forwarded_all_five_packets": (
            router_state.accepted_count == 5
            and router_state.forwarded_count == 5
            and router_state.depth == 0
        ),
        "scheduler_passed": scheduler_run.verdict is Verdict.PASS,
        "scheduler_not_blocked": scheduler_run.blocked is None,
        "session_quiescent": session.is_quiescent(
            scheduler_run.final_state
        ),
        "exact_five_packet_flow": packet_types
        == (
            ChiEvictMessage,
            ChiRetryAckMessage,
            ChiPCrdGrantMessage,
            ChiEvictMessage,
            ChiCompMessage,
        ),
        "two_req_three_rsp": Counter(
            packet.channel for packet in endpoint_packets
        )
        == Counter(
            {
                ChiChannelKind.REQ: 2,
                ChiChannelKind.RSP: 3,
            }
        ),
        "credited_reissue_disables_retry": (
            isinstance(credited_request, ChiEvictMessage)
            and not credited_request.allow_retry
            and credited_request.protocol_credit_type
            == PROTOCOL_CREDIT_TYPE
        ),
        "clean_line_evicted": (
            final_line is not None
            and final_line.state is ChiCacheState.I
            and final_line.data is None
        ),
        "directory_owner_released": (
            final.home.directory[LINE_ADDRESS].unique_owner is None
        ),
        "backing_unchanged": (
            final.home.backing == initial_coherence.home.backing
        ),
        "retry_debt_retired": not final.home.request_retry.retry_debts,
        "no_snoop_or_data_flow": not any(
            isinstance(
                packet.message,
                (
                    ChiSnpUniqueMessage,
                    ChiSnpRespMessage,
                    ChiCompDataMessage,
                    ChiCompAckMessage,
                ),
            )
            for packet in endpoint_packets
        ),
    }
    verdict = (
        Verdict.PASS
        if scheduler_run.verdict is Verdict.PASS
        and all(assertions.values())
        else Verdict.FAIL
    )
    return FlowCaseRun(
        case_id="clean-evict-retry",
        title="Clean Evict retry, P-Credit and credited reissue",
        session=session,
        initial_state=initial,
        final_state=scheduler_run.final_state,
        verdict=verdict,
        assertions=assertions,
        emissions=run.emissions,
        state_history=run.state_history,
        run=run,
    )


def _build_writeback_snoop_system() -> ResolvedChiSystem:
    builder = SystemProtocolBuilder(
        "showcase_writeback_snoop_cancellation_via_xp"
    )
    for name in ("rn0", "rn1"):
        builder.add_dut(
            VirtualDut(
                name,
                {
                    "tx_to_xp": _port(
                        "tx_to_xp",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_from_xp": _port(
                        "rx_from_xp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
    builder.add_dut(
        VirtualDut(
            "hn0",
            {
                "rx_from_xp": _port(
                    "rx_from_xp",
                    TransportDirection.RECEIVE,
                ),
                "tx_to_xp": _port(
                    "tx_to_xp",
                    TransportDirection.TRANSMIT,
                ),
            },
        )
    )
    builder.add_dut(
        VirtualDut(
            "xp0",
            {
                "from_rn0": _port(
                    "from_rn0",
                    TransportDirection.RECEIVE,
                ),
                "to_rn0": _port(
                    "to_rn0",
                    TransportDirection.TRANSMIT,
                ),
                "from_rn1": _port(
                    "from_rn1",
                    TransportDirection.RECEIVE,
                ),
                "to_rn1": _port(
                    "to_rn1",
                    TransportDirection.TRANSMIT,
                ),
                "from_hn0": _port(
                    "from_hn0",
                    TransportDirection.RECEIVE,
                ),
                "to_hn0": _port(
                    "to_hn0",
                    TransportDirection.TRANSMIT,
                ),
            },
            behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        )
    )
    rn_output = frozenset(
        (
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
            ChiChannelKind.DAT,
        )
    )
    home_output = frozenset(
        (ChiChannelKind.RSP, ChiChannelKind.SNP)
    )
    endpoint_input = frozenset(
        (ChiChannelKind.RSP, ChiChannelKind.SNP)
    )
    home_input = frozenset(
        (
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
            ChiChannelKind.DAT,
        )
    )
    connection_specs = (
        (
            "rn0_to_xp",
            VirtualDutPortRef("rn0", "tx_to_xp"),
            VirtualDutPortRef("xp0", "from_rn0"),
            rn_output,
        ),
        (
            "rn1_to_xp",
            VirtualDutPortRef("rn1", "tx_to_xp"),
            VirtualDutPortRef("xp0", "from_rn1"),
            rn_output,
        ),
        (
            "hn0_to_xp",
            VirtualDutPortRef("hn0", "tx_to_xp"),
            VirtualDutPortRef("xp0", "from_hn0"),
            home_output,
        ),
        (
            "xp_to_rn0",
            VirtualDutPortRef("xp0", "to_rn0"),
            VirtualDutPortRef("rn0", "rx_from_xp"),
            endpoint_input,
        ),
        (
            "xp_to_rn1",
            VirtualDutPortRef("xp0", "to_rn1"),
            VirtualDutPortRef("rn1", "rx_from_xp"),
            endpoint_input,
        ),
        (
            "xp_to_hn0",
            VirtualDutPortRef("xp0", "to_hn0"),
            VirtualDutPortRef("hn0", "rx_from_xp"),
            home_input,
        ),
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
            VirtualDutPortRef("hn0", "rx_from_xp"),
            AddressWindow(LINE_ADDRESS, 0x40),
        )
    )
    elaborated = builder.build().elaborate()
    duts = elaborated.spec.virtual_duts

    rn_capabilities = (
        CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES
        | CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES
        | CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
        | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES
    )
    old_owner = bind_chi_issue_h_cache_lines(
        duts["rn0"],
        REQUESTER_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "tx_to_xp": rn_output,
            "rx_from_xp": endpoint_input,
        },
        initial_lines=(
            ChiCacheLine(
                LINE_ADDRESS,
                ChiCacheState.UD,
                DIRTY_LINE_DATA,
            ),
        ),
        participant_name="dirty_old_owner",
        binding_name="rn0",
    )
    new_owner = bind_chi_issue_h_cache_lines(
        duts["rn1"],
        CONTENDER_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "tx_to_xp": rn_output,
            "rx_from_xp": endpoint_input,
        },
        participant_name="clean_unique_requester",
        binding_name="rn1",
    )
    home = ChiCoherentHomeNode(
        "writeback_snoop_home",
        HOME_NODE_ID,
        backing_core=FullLineBackingCore(
            "writeback_snoop_home.backing",
            line_bytes=64,
            initial_lines=(
                BackingLine(
                    LINE_ADDRESS,
                    STALE_BACKING_DATA,
                ),
            ),
        ),
        initial_directory=(
            ChiHomeDirectoryEntry(
                LINE_ADDRESS,
                unique_owner=REQUESTER_NODE_ID,
            ),
        ),
        allow_dirty_data_transfer=True,
    )
    home_binding = ChiParticipantBinding(
        "hn0",
        duts["hn0"],
        home,
        (
            ChiParticipantPortBinding(
                duts["hn0"].port("rx_from_xp"),
                home_input,
            ),
            ChiParticipantPortBinding(
                duts["hn0"].port("tx_to_xp"),
                home_output,
            ),
        ),
        frozenset((HOME_NODE_ID,)),
    )
    router = ChiStoreForwardRouterNode(
        "xp0",
        ingress_ports=(
            "from_rn0",
            "from_rn1",
            "from_hn0",
        ),
        egress_ports=("to_rn0", "to_rn1", "to_hn0"),
        routes=(
            ChiExactNodeRoute(
                REQUESTER_NODE_ID,
                "to_rn0",
                endpoint_input,
            ),
            ChiExactNodeRoute(
                CONTENDER_NODE_ID,
                "to_rn1",
                endpoint_input,
            ),
            ChiExactNodeRoute(
                HOME_NODE_ID,
                "to_hn0",
                home_input,
            ),
        ),
        queue_capacity=1,
    )
    router_binding = ChiParticipantBinding(
        "xp0",
        duts["xp0"],
        router,
        tuple(
            ChiParticipantPortBinding(
                duts["xp0"].port(port_name),
                channels,
            )
            for port_name, channels in (
                ("from_rn0", rn_output),
                ("from_rn1", rn_output),
                ("from_hn0", home_output),
                ("to_rn0", endpoint_input),
                ("to_rn1", endpoint_input),
                ("to_hn0", home_input),
            )
        ),
    )
    return resolve_chi_system(
        elaborated,
        facets=(
            old_owner.facets.facets[0],
            new_owner.facets.facets[0],
            ChiBehaviorFacet.from_binding(
                home_binding,
                ChiFacetKind.TRANSACTION,
            ),
            ChiBehaviorFacet.from_binding(
                router_binding,
                ChiFacetKind.FORWARDING,
            ),
        ),
        feature_contract=ChiFeatureContract(
            {},
            frozenset(
                (
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                    CHI_FEATURE_DIRTY_WRITEBACK,
                )
            ),
            {
                "requester": frozenset(("rn0", "rn1")),
            },
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
                    frozenset(("rn0", "rn1")),
                ),
            ),
        ),
        feature_address_claim=claim_name,
        participant_capabilities=(
            ChiParticipantCapability("rn0", rn_capabilities),
            ChiParticipantCapability("rn1", rn_capabilities),
            ChiParticipantCapability(
                "hn0",
                (
                    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES
                    | CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
                    | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES
                ),
            ),
        ),
        system_capabilities=frozenset(
            (
                CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
                CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
                CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
            )
        ),
    )


def run_writeback_snoop_cancellation() -> FlowCaseRun:
    """Route a scheduler-held WriteBackFull around a same-line Snoop.

    The scenario selects public scheduler moves so the original
    WriteBackFull reaches its RN-to-XP receiver but is not captured by XP.
    CleanUnique then traverses the other CHI channels and completes before
    the held REQ is released.  Every packet, hop, and participant transition
    remains production-model evidence; the hold is ordering control, not a
    cycle-latency claim.
    """

    resolved = _build_writeback_snoop_system()
    session = ChiCoherenceNetworkSession.from_resolved(resolved)
    initial = session.initial_state()
    state = initial
    emissions: list[ChiCoherenceNetworkEvent] = []
    state_history = [initial]

    def commit(action, label: str, *, required: bool = True) -> bool:
        nonlocal state
        transition = session.step(state, action)
        if transition.fault is not None:
            raise RuntimeError(
                f"{label} faulted: {transition.fault.rule}: "
                f"{transition.fault.reason}"
            )
        if transition.blocked is not None:
            if not required:
                return False
            raise RuntimeError(
                f"{label} blocked: {transition.blocked.reason}"
            )
        if len(transition.emissions) != 1:
            raise RuntimeError(
                f"{label} must commit exactly one observable scheduler step"
            )
        state = transition.state
        emissions.extend(transition.emissions)
        state_history.append(state)
        return True

    commit(
        ChiSubmitWriteBackFull(
            REQUESTER_NODE_ID,
            ChiWriteBackFullMessage(
                EVICT_TXN_ID,
                LINE_ADDRESS,
            ),
        ),
        "issue WriteBackFull",
    )
    commit(
        ChiAdvanceCoherenceNetwork("egress.enqueue"),
        "enqueue WriteBackFull on the RN0-to-XP REQ path",
    )
    commit(
        ChiSubmitCleanUnique(
            CONTENDER_NODE_ID,
            ChiCleanUniqueMessage(
                CLEAN_UNIQUE_TXN_ID,
                LINE_ADDRESS,
            ),
        ),
        "issue CleanUnique",
    )
    commit(
        ChiAdvanceCoherenceNetwork("egress.enqueue"),
        "enqueue CleanUnique on the RN1-to-XP REQ path",
    )

    held_candidate = "capture.rn0_to_xp.req"
    selected_candidates = tuple(
        candidate
        for candidate in session.scheduler_candidates
        if candidate != held_candidate
    )

    def clean_unique_retired() -> bool:
        coherence = state.coherence
        entry = coherence.home.directory[LINE_ADDRESS]
        return (
            entry.unique_owner == CONTENDER_NODE_ID
            and not coherence.expected_clean_unique_completions
            and not coherence.home.pending
        )

    for _round in range(256):
        if clean_unique_retired():
            break
        progressed = False
        for candidate in selected_candidates:
            progressed = (
                commit(
                    ChiAdvanceCoherenceNetwork(candidate),
                    f"advance {candidate}",
                    required=False,
                )
                or progressed
            )
            if clean_unique_retired():
                break
        if not progressed:
            raise RuntimeError(
                "selected CHI moves cannot complete CleanUnique while "
                "WriteBackFull remains held"
            )
    else:
        raise RuntimeError(
            "selected CHI moves exhausted the CleanUnique progress budget"
        )

    before_release = state.coherence
    old_owner_after_snoop = before_release.request_nodes[
        REQUESTER_NODE_ID
    ]
    old_line_after_snoop = old_owner_after_snoop.line_at(
        LINE_ADDRESS
    )
    pending_after_snoop = old_owner_after_snoop.pending_copybacks[
        EVICT_TXN_ID
    ]
    new_line = before_release.request_nodes[
        CONTENDER_NODE_ID
    ].line_at(
        LINE_ADDRESS
    )
    before_late_request_entry = before_release.home.directory[
        LINE_ADDRESS
    ]
    before_late_request_backing = before_release.home.backing.line_at(
        LINE_ADDRESS
    )

    scheduled = session.run_until_quiescent(
        state,
        max_steps=2048,
    )
    emissions.extend(scheduled.emissions)
    state_history.extend(scheduled.state_history[1:])
    final_state = scheduled.final_state
    final = final_state.coherence

    endpoint_records = tuple(
        (index, event)
        for index, event in enumerate(emissions)
        if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
    )
    endpoint_packets = tuple(
        event.packet
        for _index, event in endpoint_records
        if event.packet is not None
    )
    packet_types = tuple(
        type(packet.message) for packet in endpoint_packets
    )
    snoop_response = next(
        packet.message
        for packet in endpoint_packets
        if isinstance(packet.message, ChiSnpRespDataMessage)
    )
    writeback_event_index = next(
        index
        for index, event in endpoint_records
        if (
            event.packet is not None
            and isinstance(
                event.packet.message,
                ChiWriteBackFullMessage,
            )
        )
    )
    comp_ack_event_index = next(
        index
        for index, event in endpoint_records
        if (
            event.packet is not None
            and isinstance(event.packet.message, ChiCompAckMessage)
        )
    )
    home_pending = next(
        iter(
            state_history[
                writeback_event_index + 1
            ].coherence.home.pending_copybacks.values()
        )
    )
    cancellation_response = next(
        packet
        for packet in endpoint_packets
        if isinstance(packet.message, ChiCompDBIDRespMessage)
    )
    cancellation_data_packet = next(
        produced
        for _index, event in endpoint_records
        if event.packet is cancellation_response
        for produced in event.produced
        if isinstance(produced.message, ChiCopyBackWrDataMessage)
    )
    cancellation_data = cancellation_data_packet.message
    final_entry = final.home.directory[LINE_ADDRESS]
    final_backing = final.home.backing.line_at(LINE_ADDRESS)
    router_state = final_state.network.routers["xp0"]

    assertions = {
        "resolved_topology_closed": resolved.is_closed,
        "multi_requester_authority_closed": (
            resolved.feature_contract.role_members("requester")
            == ("rn0", "rn1")
            and resolved.feature_contract.role_members("snoopee")
            == ("rn0", "rn1")
        ),
        "one_explicit_xp_forwarder": (
            tuple(
                binding.name
                for binding in resolved.forwarding_bindings
            )
            == ("xp0",)
        ),
        "all_feature_flows_cross_xp_in_two_hops": all(
            len(route) == 2
            and session.network.hops[route[0]].receiver.dut == "xp0"
            and session.network.hops[route[1]].transmitter.dut == "xp0"
            for route in session.route_by_packet_key.values()
        ),
        "selected_scheduler_completed": (
            scheduled.verdict is Verdict.PASS
            and scheduled.blocked is None
        ),
        "exact_eight_packet_endpoint_flow": packet_types
        == (
            ChiCleanUniqueMessage,
            ChiSnpCleanInvalidMessage,
            ChiSnpRespDataMessage,
            ChiCompMessage,
            ChiCompAckMessage,
            ChiWriteBackFullMessage,
            ChiCompDBIDRespMessage,
            ChiCopyBackWrDataMessage,
        ),
        "writeback_req_held_until_clean_unique_retired": (
            comp_ack_event_index < writeback_event_index
        ),
        "every_endpoint_packet_crossed_xp": all(
            any("to_xp@" in item for item in event.lineage)
            and any(item.startswith("xp_to_") for item in event.lineage)
            for _index, event in endpoint_records
        ),
        "xp_forwarded_all_eight_packets": (
            router_state.accepted_count == 8
            and router_state.forwarded_count == 8
            and router_state.depth == 0
        ),
        "old_owner_invalidated": (
            old_line_after_snoop is not None
            and old_line_after_snoop.state is ChiCacheState.I
        ),
        "pending_writeback_marked_canceled": (
            pending_after_snoop.outcome
            is ChiRnCopyBackOutcome.CANCELED_I
        ),
        "snoop_carries_dirty_payload": (
            getattr(snoop_response, "data", None)
            == DIRTY_LINE_DATA
            and getattr(snoop_response, "response", None)
            is ChiRespCode.I_PD
        ),
        "clean_unique_installs_new_owner": (
            new_line is not None
            and new_line.state is ChiCacheState.UCE
            and before_late_request_entry.unique_owner
            == CONTENDER_NODE_ID
        ),
        "snoop_payload_committed_once": (
            before_late_request_backing is not None
            and before_late_request_backing.data
            == DIRTY_LINE_DATA
        ),
        "late_request_uses_snoop_cancel_admission": (
            home_pending.admission
            is ChiHomeCopyBackAdmission.SNOOP_CANCELED
        ),
        "home_emits_comp_dbid_response": isinstance(
            cancellation_response.message,
            ChiCompDBIDRespMessage,
        ),
        "rn_emits_zero_byte_cancel_data": (
            isinstance(
                cancellation_data,
                ChiCopyBackWrDataMessage,
            )
            and cancellation_data.response is ChiRespCode.I
            and cancellation_data.data == 0
            and cancellation_data.byte_enable == 0
        ),
        "late_cancel_does_not_overwrite_directory": (
            final_entry == before_late_request_entry
        ),
        "late_cancel_does_not_overwrite_backing": (
            final_backing == before_late_request_backing
        ),
        "copyback_expectations_retired": (
            not final.expected_writeback_dbid_responses
            and not final.expected_copyback_data
        ),
        "session_quiescent": session.is_quiescent(final_state),
        "coherence_invariants_hold": not (
            ChiCoherenceInvariantMonitor().explain(
                final.home,
                final.request_nodes,
            )
        ),
    }
    verdict = (
        Verdict.PASS
        if scheduled.verdict is Verdict.PASS
        and all(assertions.values())
        else Verdict.FAIL
    )
    run: SemanticRun[object, object, object] = SemanticRun(
        verdict,
        final_state,
        tuple(emissions),
        violations=scheduled.violations,
        state_history=tuple(state_history),
        blocked=scheduled.blocked,
    )
    return FlowCaseRun(
        case_id="writeback-snoop-cancel",
        title=(
            "Dirty WriteBackFull canceled by pre-response "
            "same-line Snoop"
        ),
        session=session,
        initial_state=initial,
        final_state=final_state,
        verdict=verdict,
        assertions=assertions,
        emissions=run.emissions,
        state_history=run.state_history,
        run=run,
    )


def run_progress_cases() -> Mapping[str, FlowCaseRun]:
    """Execute the progress gallery in stable presentation order."""

    cases = (
        run_clean_evict_retry(),
        run_writeback_snoop_cancellation(),
    )
    return MappingProxyType({case.case_id: case for case in cases})


__all__ = [
    "FlowCaseRun",
    "run_clean_evict_retry",
    "run_progress_cases",
    "run_writeback_snoop_cancellation",
]
