"""Executable CHI progress and interference cases for the flow gallery.

The clean-Evict case uses a resolved two-node topology and the automatic
coherence-network scheduler.  The dirty-WriteBackFull case intentionally uses
the participant-level system runtime: delaying the copyback request while a
second requester completes CleanUnique is the scenario-controlled
interleaving under study.  In both cases every protocol packet retained by
the result is emitted by a production model transition; this module does not
manufacture a packet trace.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_EVICT_HOME_CAPABILITIES,
    CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
    CHI_REQUEST_RETRY_HOME_CAPABILITIES,
    CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiFacetKind,
    ChiHomeCopyBackAdmission,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiRnCopyBackOutcome,
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
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiRespCode,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
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
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceInvariantMonitor,
    ChiCoherenceNetworkEvent,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
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
    ChiReqChannelProfile,
    ChiRspChannelProfile,
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
    observation_steps: tuple["FlowObservationStep", ...] = ()

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
        object.__setattr__(
            self,
            "observation_steps",
            tuple(self.observation_steps),
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


@dataclass(frozen=True)
class FlowObservationStep:
    """One accepted participant transition retained for exact projection."""

    label: str
    before_state: object
    after_state: object
    accepted_packet: ChiNetworkPacket | None
    produced: tuple[ChiNetworkPacket, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("flow observation step requires a label")
        if (
            self.accepted_packet is not None
            and not isinstance(self.accepted_packet, ChiNetworkPacket)
        ):
            raise TypeError("accepted_packet must be a CHI network packet")
        produced = tuple(self.produced)
        if any(not isinstance(item, ChiNetworkPacket) for item in produced):
            raise TypeError("produced must contain CHI network packets")
        object.__setattr__(self, "produced", produced)


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
    channel: ChiChannelKind,
) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=(
            ChiReqChannelProfile(
                ChiIssueHReqProfile(),
                (1,),
                f"{name}.req",
            )
            if channel is ChiChannelKind.REQ
            else None
        ),
        response=(
            ChiRspChannelProfile(
                ChiIssueHRspProfile(),
                1,
                f"{name}.rsp",
            )
            if channel is ChiChannelKind.RSP
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
    builder.connect_transport(
        "evict_request",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("rn0", "tx_req"),
        VirtualDutPortRef("hn0", "rx_req"),
        profile=_link_profile(
            "evict_request",
            ChiChannelKind.REQ,
        ),
    )
    builder.connect_transport(
        "evict_completion",
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        VirtualDutPortRef("hn0", "tx_rsp"),
        VirtualDutPortRef("rn0", "rx_rsp"),
        profile=_link_profile(
            "evict_completion",
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
    return resolve_chi_system(
        elaborated,
        facets=(
            requester.facets.facets[0],
            ChiBehaviorFacet.from_binding(
                home_binding,
                ChiFacetKind.TRANSACTION,
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
    assertions = {
        "resolved_topology_closed": resolved.is_closed,
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


def _build_writeback_snoop_session() -> ChiCoherenceSession:
    old_owner = build_chi_cache_participant_fixture(
        "dirty_old_owner",
        REQUESTER_NODE_ID,
        HOME_NODE_ID,
        initial_lines=(
            ChiCacheLine(
                LINE_ADDRESS,
                ChiCacheState.UD,
                DIRTY_LINE_DATA,
            ),
        ),
    )
    new_owner = build_chi_cache_participant_fixture(
        "clean_unique_requester",
        CONTENDER_NODE_ID,
        HOME_NODE_ID,
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
    return ChiCoherenceSession(
        "showcase_writeback_snoop_cancellation",
        home,
        {
            REQUESTER_NODE_ID: old_owner,
            CONTENDER_NODE_ID: new_owner,
        },
        enabled_features=frozenset(
            (
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                CHI_FEATURE_DIRTY_WRITEBACK,
            )
        ),
        requester_node_ids=frozenset(
            (REQUESTER_NODE_ID, CONTENDER_NODE_ID)
        ),
        snoopee_node_ids=frozenset(
            (REQUESTER_NODE_ID, CONTENDER_NODE_ID)
        ),
    )


def _accepted_step(
    session: ChiCoherenceSession,
    state,
    action,
    *,
    label: str,
):
    transition = session.step(state, action)
    if transition.fault is not None:
        raise RuntimeError(
            f"{label} faulted: {transition.fault.rule}: "
            f"{transition.fault.reason}"
        )
    if transition.blocked is not None:
        raise RuntimeError(
            f"{label} blocked: {transition.blocked.reason}"
        )
    return transition


def run_writeback_snoop_cancellation() -> FlowCaseRun:
    """Run the scenario-owned delayed-request cancellation interleaving.

    The original WriteBackFull packet is held by the scenario while
    CleanUnique invalidates the old owner and transfers its dirty payload.
    Delivering that already-emitted request afterward causes the Home and RN
    models to produce the explicit zero-byte cancellation DAT path.
    """

    session = _build_writeback_snoop_session()
    initial = session.initial_state()
    state = initial
    emissions: list[object] = []
    state_history: list[object] = [initial]
    observation_steps: list[FlowObservationStep] = []

    def commit(action, label: str):
        nonlocal state
        before_state = state
        transition = _accepted_step(
            session,
            state,
            action,
            label=label,
        )
        state = transition.state
        emissions.extend(transition.emissions)
        state_history.append(state)
        observation_steps.append(
            FlowObservationStep(
                label=label,
                before_state=before_state,
                after_state=state,
                accepted_packet=(
                    action.packet
                    if isinstance(action, ChiDeliverCoherencePacket)
                    else None
                ),
                produced=transition.emissions,
            )
        )
        return transition

    writeback_issued = commit(
        ChiSubmitWriteBackFull(
            REQUESTER_NODE_ID,
            ChiWriteBackFullMessage(
                EVICT_TXN_ID,
                LINE_ADDRESS,
            ),
        ),
        "issue WriteBackFull",
    )
    delayed_writeback = writeback_issued.emissions[0]
    clean_unique_issued = commit(
        ChiSubmitCleanUnique(
            CONTENDER_NODE_ID,
            ChiCleanUniqueMessage(
                CLEAN_UNIQUE_TXN_ID,
                LINE_ADDRESS,
            ),
        ),
        "issue CleanUnique",
    )
    clean_unique_at_home = commit(
        ChiDeliverCoherencePacket(
            clean_unique_issued.emissions[0]
        ),
        "deliver CleanUnique to Home",
    )
    old_owner_snooped = commit(
        ChiDeliverCoherencePacket(
            clean_unique_at_home.emissions[0]
        ),
        "deliver invalidating Snoop",
    )
    old_owner_after_snoop = state.request_nodes[REQUESTER_NODE_ID]
    old_line_after_snoop = old_owner_after_snoop.line_at(
        LINE_ADDRESS
    )
    pending_after_snoop = old_owner_after_snoop.pending_copybacks[
        EVICT_TXN_ID
    ]
    snoop_response = old_owner_snooped.emissions[0].message

    clean_unique_collected = commit(
        ChiDeliverCoherencePacket(
            old_owner_snooped.emissions[0]
        ),
        "return dirty Snoop response",
    )
    new_owner_completed = commit(
        ChiDeliverCoherencePacket(
            clean_unique_collected.emissions[0]
        ),
        "deliver CleanUnique completion",
    )
    clean_unique_retired = commit(
        ChiDeliverCoherencePacket(
            new_owner_completed.emissions[0]
        ),
        "deliver CleanUnique CompAck",
    )
    new_line = state.request_nodes[CONTENDER_NODE_ID].line_at(
        LINE_ADDRESS
    )
    before_late_request_entry = state.home.directory[LINE_ADDRESS]
    before_late_request_backing = state.home.backing.line_at(
        LINE_ADDRESS
    )

    canceled_at_home = commit(
        ChiDeliverCoherencePacket(delayed_writeback),
        "deliver late WriteBackFull request",
    )
    home_pending = next(
        iter(state.home.pending_copybacks.values())
    )
    cancellation_response = canceled_at_home.emissions[0]
    cancel_sent = commit(
        ChiDeliverCoherencePacket(cancellation_response),
        "deliver cancellation response",
    )
    cancellation_data_packet = cancel_sent.emissions[0]
    cancellation_data = cancellation_data_packet.message
    final_transition = commit(
        ChiDeliverCoherencePacket(cancellation_data_packet),
        "deliver cancellation data",
    )
    final = final_transition.state
    final_entry = final.home.directory[LINE_ADDRESS]
    final_backing = final.home.backing.line_at(LINE_ADDRESS)

    assertions = {
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
        "session_quiescent": session.is_quiescent(final),
        "coherence_invariants_hold": not (
            ChiCoherenceInvariantMonitor().explain(
                final.home,
                final.request_nodes,
            )
        ),
    }
    verdict = (
        Verdict.PASS
        if all(assertions.values())
        else Verdict.FAIL
    )
    run: SemanticRun[object, object, object] = SemanticRun(
        verdict,
        final,
        tuple(emissions),
        state_history=tuple(state_history),
    )
    return FlowCaseRun(
        case_id="writeback-snoop-cancel",
        title=(
            "Dirty WriteBackFull canceled by pre-response "
            "same-line Snoop"
        ),
        session=session,
        initial_state=initial,
        final_state=final,
        verdict=verdict,
        assertions=assertions,
        emissions=run.emissions,
        state_history=run.state_history,
        run=run,
        observation_steps=tuple(observation_steps),
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
    "FlowObservationStep",
    "run_clean_evict_retry",
    "run_progress_cases",
    "run_writeback_snoop_cancellation",
]
