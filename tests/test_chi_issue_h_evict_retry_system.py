from __future__ import annotations

from collections import Counter
from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiRequestRetryHomeState,
    ChiRequestRetryPhase,
    ChiRequestRetryRequesterState,
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
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiCompMessage,
    ChiEvictMessage,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiReadUniqueMessage,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_EVICT,
    CHI_FEATURE_CLEAN_EVICT_RETRY,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,
    CHI_SYSTEM_CLEAN_EVICT_RETRY_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceInvariantMonitor,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
    ChiGrantCoherentHomePCredit,
    ChiHomeAuthority,
    ChiRetryCoherentRequest,
    ChiSubmitCoherentRead,
    ChiSubmitEvict,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import Verdict
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


class ChiIssueHEvictRetrySystemTest(unittest.TestCase):
    REQUESTER = 0x07
    CONTENDER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xE71C7
    TXN_ID = 0x31
    CONTENDER_TXN_ID = 0x32
    CREDIT_TYPE = 5

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_fault_rule(self, transition, expected_rule: str) -> None:
        self.assertIsNotNone(transition.fault)
        self.assertEqual(
            expected_rule,
            transition.fault.rule.rsplit(".", 1)[-1],
        )

    def build_home(
        self,
        *,
        evict_retry: bool = True,
        read_unique_retry: bool = False,
        transaction_capacity: int = 1,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.REQUESTER,
                ),
            ),
            transaction_capacity=transaction_capacity,
            evict_retry_policy=(
                (
                    lambda request, _state: (
                        self.CREDIT_TYPE
                        if request.transaction_id == self.TXN_ID
                        else None
                    )
                )
                if evict_retry
                else None
            ),
            retry_policy=(
                (lambda _request, _state: self.CREDIT_TYPE)
                if read_unique_retry
                else None
            ),
            default_protocol_credit_type=self.CREDIT_TYPE,
        )

    def build_session(
        self,
        *,
        evict_retry: bool = True,
        read_unique_retry: bool = False,
        with_contender: bool = False,
        enabled_features: frozenset | None = None,
    ) -> ChiCoherenceSession:
        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
            ),
        )
        nodes = {self.REQUESTER: requester}
        if with_contender:
            nodes[self.CONTENDER] = build_chi_cache_participant_fixture(
                "contender",
                self.CONTENDER,
                self.HOME,
            )
        if enabled_features is None:
            enabled_features = frozenset(
                (
                    CHI_FEATURE_CLEAN_EVICT,
                    CHI_FEATURE_CLEAN_EVICT_RETRY,
                    *(
                        (CHI_FEATURE_CLEAN_READ_UNIQUE,)
                        if with_contender
                        else ()
                    ),
                    *(
                        (CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,)
                        if read_unique_retry
                        else ()
                    ),
                )
            )
        return ChiCoherenceSession(
            "evict_retry",
            self.build_home(
                evict_retry=evict_retry,
                read_unique_retry=read_unique_retry,
            ),
            nodes,
            enabled_features=enabled_features,
            requester_node_ids=frozenset(nodes),
            snoopee_node_ids=frozenset(nodes),
        )

    def request(self) -> ChiEvictMessage:
        return ChiEvictMessage(self.TXN_ID, self.ADDRESS)

    def drive_to_credited_reissue(self, session):
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        rejected = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        self.assertIsInstance(
            rejected.emissions[0].message,
            ChiRetryAckMessage,
        )
        ack_seen = self.apply(
            session,
            rejected.state,
            ChiDeliverCoherencePacket(rejected.emissions[0]),
        )
        granted = self.apply(
            session,
            ack_seen.state,
            ChiGrantCoherentHomePCredit(),
        )
        credit_seen = self.apply(
            session,
            granted.state,
            ChiDeliverCoherencePacket(granted.emissions[0]),
        )
        retried = self.apply(
            session,
            credit_seen.state,
            ChiRetryCoherentRequest(self.REQUESTER, self.TXN_ID),
        )
        return issued, rejected, ack_seen, granted, credit_seen, retried

    def test_policy_feature_gate_is_opcode_specific(self) -> None:
        base = frozenset((CHI_FEATURE_CLEAN_EVICT,))
        with self.assertRaisesRegex(
            ValueError,
            "Evict retry policy requires the Evict Retry feature",
        ):
            self.build_session(enabled_features=base)

        modifier = frozenset(
            (
                CHI_FEATURE_CLEAN_EVICT,
                CHI_FEATURE_CLEAN_EVICT_RETRY,
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "Evict Retry feature requires a configured coherent Home",
        ):
            self.build_session(
                evict_retry=False,
                enabled_features=modifier,
            )

        both_modifiers = frozenset(
            (
                CHI_FEATURE_CLEAN_EVICT,
                CHI_FEATURE_CLEAN_EVICT_RETRY,
                CHI_FEATURE_CLEAN_READ_UNIQUE,
                CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "Evict Retry feature requires a configured coherent Home",
        ):
            self.build_session(
                evict_retry=False,
                read_unique_retry=True,
                enabled_features=both_modifiers,
            )

    def test_packet_delivery_retry_and_exact_completion(self) -> None:
        session = self.build_session()
        initial = session.initial_state()
        initial_directory = initial.home.directory
        initial_backing = initial.home.backing
        initial_snoop_id = initial.home.next_snoop_transaction_id
        initial_dbid = initial.home.next_data_buffer_id

        issued, rejected, _, _, _, retried = (
            self.drive_to_credited_reissue(session)
        )

        requester_after_issue = issued.state.request_nodes[self.REQUESTER]
        line = requester_after_issue.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertFalse(rejected.state.expected_evict_completions)
        self.assertEqual(initial_directory, rejected.state.home.directory)
        self.assertEqual(initial_backing, rejected.state.home.backing)
        self.assertEqual(
            initial_snoop_id,
            rejected.state.home.next_snoop_transaction_id,
        )
        self.assertEqual(
            initial_dbid,
            rejected.state.home.next_data_buffer_id,
        )
        self.assertFalse(rejected.state.home.pending)
        self.assertFalse(rejected.state.home.pending_writebacks)

        credited_request = retried.emissions[0]
        self.assertIsInstance(credited_request.message, ChiEvictMessage)
        self.assertFalse(credited_request.message.allow_retry)
        self.assertEqual(
            self.CREDIT_TYPE,
            credited_request.message.protocol_credit_type,
        )
        accepted = self.apply(
            session,
            retried.state,
            ChiDeliverCoherencePacket(credited_request),
        )
        completion = accepted.emissions[0]
        self.assertIsInstance(completion.message, ChiCompMessage)
        self.assertEqual(
            completion,
            accepted.state.expected_evict_completions[
                (self.REQUESTER, self.TXN_ID)
            ],
        )

        forged = ChiNetworkPacket.response(
            replace(completion.message, data_buffer_id=1),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        rejected_forge = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(forged),
        )
        self.assert_fault_rule(
            rejected_forge,
            "evict_completion_correlation",
        )
        self.assertEqual(accepted.state, rejected_forge.state)

        retired = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(retired.state.expected_evict_completions)
        self.assertEqual(initial_backing, retired.state.home.backing)
        self.assertEqual(
            1,
            retired.state.home.request_retry.retry_ack_count,
        )
        self.assertEqual(1, retired.state.home.request_retry.grant_count)
        self.assertEqual(
            1,
            retired.state.home.request_retry.consumed_count,
        )

        replay = session.step(
            retired.state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assert_fault_rule(replay, "dataless_completion_correlation")
        self.assertEqual(retired.state, replay.state)

    def test_replayed_initial_evict_is_an_atomic_system_fault(self) -> None:
        session = self.build_session()
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        initial_request = issued.emissions[0]
        rejected = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(initial_request),
        )
        granted = self.apply(
            session,
            rejected.state,
            ChiGrantCoherentHomePCredit(),
        )
        credit_seen = self.apply(
            session,
            granted.state,
            ChiDeliverCoherencePacket(granted.emissions[0]),
        )

        before_ack = session.step(
            credit_seen.state,
            ChiDeliverCoherencePacket(initial_request),
        )
        self.assert_fault_rule(before_ack, "retry_request_replay")
        self.assertEqual(credit_seen.state, before_ack.state)
        self.assertFalse(before_ack.emissions)

        ack_seen = self.apply(
            session,
            credit_seen.state,
            ChiDeliverCoherencePacket(rejected.emissions[0]),
        )
        self.assertIs(
            ChiRequestRetryPhase.WAIT_RETRY_CREDIT,
            ack_seen.state.request_nodes[
                self.REQUESTER
            ].request_retry.entries[self.TXN_ID].phase,
        )
        after_ack = session.step(
            ack_seen.state,
            ChiDeliverCoherencePacket(initial_request),
        )
        self.assert_fault_rule(after_ack, "retry_request_delivery")
        self.assertEqual(ack_seen.state, after_ack.state)
        self.assertFalse(after_ack.emissions)

    def test_retry_response_packets_require_exact_home_evidence(
        self,
    ) -> None:
        session = self.build_session()
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        forged_ack = ChiNetworkPacket.response(
            ChiRetryAckMessage(self.TXN_ID, self.CREDIT_TYPE),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        early_ack = session.step(
            issued.state,
            ChiDeliverCoherencePacket(forged_ack),
        )
        self.assert_fault_rule(early_ack, "retry_ack_correlation")

        rejected = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        exact_ack = rejected.emissions[0]
        self.assertEqual(
            exact_ack,
            rejected.state.expected_retry_acks[
                (self.REQUESTER, self.TXN_ID)
            ],
        )
        wrong_ack = ChiNetworkPacket.response(
            replace(
                exact_ack.message,
                protocol_credit_type=(self.CREDIT_TYPE + 1) % 16,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        mismatched_ack = session.step(
            rejected.state,
            ChiDeliverCoherencePacket(wrong_ack),
        )
        self.assert_fault_rule(
            mismatched_ack,
            "retry_ack_correlation",
        )

        granted = self.apply(
            session,
            rejected.state,
            ChiGrantCoherentHomePCredit(),
        )
        exact_grant = granted.emissions[0]
        self.assertIn(exact_grant, granted.state.expected_pcredit_grants)
        self.assertIn(
            (self.REQUESTER, self.TXN_ID),
            granted.state.expected_retry_acks,
        )
        wrong_grant = ChiNetworkPacket.response(
            ChiPCrdGrantMessage((self.CREDIT_TYPE + 1) % 16),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        mismatched_grant = session.step(
            granted.state,
            ChiDeliverCoherencePacket(wrong_grant),
        )
        self.assert_fault_rule(
            mismatched_grant,
            "pcredit_grant_correlation",
        )

        credit_seen = self.apply(
            session,
            granted.state,
            ChiDeliverCoherencePacket(exact_grant),
        )
        self.assertFalse(credit_seen.state.expected_pcredit_grants)
        self.assertTrue(credit_seen.state.expected_retry_acks)
        replayed_grant = session.step(
            credit_seen.state,
            ChiDeliverCoherencePacket(exact_grant),
        )
        self.assert_fault_rule(
            replayed_grant,
            "pcredit_grant_correlation",
        )

        ack_seen = self.apply(
            session,
            credit_seen.state,
            ChiDeliverCoherencePacket(exact_ack),
        )
        self.assertFalse(ack_seen.state.expected_retry_acks)
        retried = self.apply(
            session,
            ack_seen.state,
            ChiRetryCoherentRequest(self.REQUESTER, self.TXN_ID),
        )
        accepted = self.apply(
            session,
            retried.state,
            ChiDeliverCoherencePacket(retried.emissions[0]),
        )
        retired = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(accepted.emissions[0]),
        )
        self.assertTrue(session.is_quiescent(retired.state))

    def test_retry_ack_and_reissue_gate_the_retained_opcode(self) -> None:
        read_retry_only = self.build_session(
            evict_retry=False,
            read_unique_retry=True,
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_EVICT,
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
                )
            ),
        )
        evict_issued = self.apply(
            read_retry_only,
            read_retry_only.initial_state(),
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        forged_evict_ack = ChiNetworkPacket.response(
            ChiRetryAckMessage(self.TXN_ID, self.CREDIT_TYPE),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        evict_ack = read_retry_only.step(
            evict_issued.state,
            ChiDeliverCoherencePacket(forged_evict_ack),
        )
        self.assert_fault_rule(evict_ack, "retry_feature")
        evict_reissue = read_retry_only.step(
            evict_issued.state,
            ChiRetryCoherentRequest(self.REQUESTER, self.TXN_ID),
        )
        self.assert_fault_rule(evict_reissue, "retry_feature")

        evict_retry_only = self.build_session(with_contender=True)
        read_issued = self.apply(
            evict_retry_only,
            evict_retry_only.initial_state(),
            ChiSubmitCoherentRead(
                self.CONTENDER,
                ChiReadUniqueMessage(
                    self.CONTENDER_TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        forged_read_ack = ChiNetworkPacket.response(
            ChiRetryAckMessage(
                self.CONTENDER_TXN_ID,
                self.CREDIT_TYPE,
            ),
            source_id=self.HOME,
            target_id=self.CONTENDER,
        )
        read_ack = evict_retry_only.step(
            read_issued.state,
            ChiDeliverCoherencePacket(forged_read_ack),
        )
        self.assert_fault_rule(read_ack, "retry_feature")
        read_reissue = evict_retry_only.step(
            read_issued.state,
            ChiRetryCoherentRequest(
                self.CONTENDER,
                self.CONTENDER_TXN_ID,
            ),
        )
        self.assert_fault_rule(read_reissue, "retry_feature")

    def test_credited_evict_rejects_wrong_credit_or_no_reservation(
        self,
    ) -> None:
        session = self.build_session()
        *_, retried = self.drive_to_credited_reissue(session)
        correct_packet = retried.emissions[0]
        correct_request = correct_packet.message
        assert isinstance(correct_request, ChiEvictMessage)

        no_reservation_home = replace(
            retried.state.home,
            request_retry=ChiRequestRetryHomeState(),
        )
        no_reservation_state = replace(
            retried.state,
            home=no_reservation_home,
        )
        missing = session.step(
            no_reservation_state,
            ChiDeliverCoherencePacket(correct_packet),
        )
        self.assert_fault_rule(missing, "missing_reservation")
        self.assertEqual(no_reservation_state, missing.state)

        wrong_credit_type = (self.CREDIT_TYPE + 1) % 16
        wrong_request = replace(
            correct_request,
            protocol_credit_type=wrong_credit_type,
        )
        requester = retried.state.request_nodes[self.REQUESTER]
        retry_entry = requester.request_retry.entries[self.TXN_ID]
        wrong_entry = replace(
            retry_entry,
            current_request=wrong_request,
            protocol_credit_type=wrong_credit_type,
        )
        wrong_retry_state = ChiRequestRetryRequesterState(
            {self.TXN_ID: wrong_entry},
            requester.request_retry.protocol_credits,
        )
        wrong_requester = replace(
            requester,
            pending_transactions={self.TXN_ID: wrong_request},
            request_retry=wrong_retry_state,
        )
        wrong_state = replace(
            retried.state,
            request_nodes={self.REQUESTER: wrong_requester},
        )
        wrong_packet = ChiNetworkPacket.request(
            wrong_request,
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )
        wrong_credit = session.step(
            wrong_state,
            ChiDeliverCoherencePacket(wrong_packet),
        )
        self.assert_fault_rule(wrong_credit, "missing_reservation")
        self.assertEqual(wrong_state, wrong_credit.state)

    def test_waiting_evict_preserves_correlation_across_same_line_snoop(
        self,
    ) -> None:
        session = self.build_session(with_contender=True)
        state = session.initial_state()

        evict_issued = self.apply(
            session,
            state,
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        evict_rejected = self.apply(
            session,
            evict_issued.state,
            ChiDeliverCoherencePacket(evict_issued.emissions[0]),
        )
        retry_ack_seen = self.apply(
            session,
            evict_rejected.state,
            ChiDeliverCoherencePacket(evict_rejected.emissions[0]),
        )

        contender_issued = self.apply(
            session,
            retry_ack_seen.state,
            ChiSubmitCoherentRead(
                self.CONTENDER,
                ChiReadUniqueMessage(
                    self.CONTENDER_TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        contender_accepted = self.apply(
            session,
            contender_issued.state,
            ChiDeliverCoherencePacket(contender_issued.emissions[0]),
        )
        snoop = contender_accepted.emissions[0]
        self.assertIsInstance(snoop.message, ChiSnpUniqueMessage)
        self.assertEqual(self.REQUESTER, snoop.target_id)

        snooped = self.apply(
            session,
            contender_accepted.state,
            ChiDeliverCoherencePacket(snoop),
        )
        self.assertIsInstance(
            snooped.emissions[0].message,
            ChiSnpRespMessage,
        )
        waiting = snooped.state.request_nodes[self.REQUESTER]
        self.assertIsInstance(
            waiting.pending_transactions[self.TXN_ID],
            ChiEvictMessage,
        )
        self.assertIs(
            ChiRequestRetryPhase.WAIT_RETRY_CREDIT,
            waiting.request_retry.entries[self.TXN_ID].phase,
        )
        line = waiting.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)

        contender_completed = self.apply(
            session,
            snooped.state,
            ChiDeliverCoherencePacket(snooped.emissions[0]),
        )
        contender_installed = self.apply(
            session,
            contender_completed.state,
            ChiDeliverCoherencePacket(
                contender_completed.emissions[0]
            ),
        )
        self.assertIsInstance(
            contender_installed.emissions[0].message,
            ChiCompAckMessage,
        )
        contender_retired = self.apply(
            session,
            contender_installed.state,
            ChiDeliverCoherencePacket(
                contender_installed.emissions[0]
            ),
        )
        self.assertEqual(
            self.CONTENDER,
            contender_retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )

        granted = self.apply(
            session,
            contender_retired.state,
            ChiGrantCoherentHomePCredit(),
        )
        credit_seen = self.apply(
            session,
            granted.state,
            ChiDeliverCoherencePacket(granted.emissions[0]),
        )
        retried = self.apply(
            session,
            credit_seen.state,
            ChiRetryCoherentRequest(self.REQUESTER, self.TXN_ID),
        )
        accepted = self.apply(
            session,
            retried.state,
            ChiDeliverCoherencePacket(retried.emissions[0]),
        )
        retired = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(accepted.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        self.assertEqual(
            self.CONTENDER,
            retired.state.home.directory[self.ADDRESS].unique_owner,
        )
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    @staticmethod
    def port(
        name: str,
        direction: TransportDirection,
    ) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    @staticmethod
    def link_profile(
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

    def build_resolved(self):
        builder = SystemProtocolBuilder("chi_evict_retry_direct")
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_req": self.port(
                        "tx_req",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_rsp": self.port(
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
                    "rx_req": self.port(
                        "rx_req",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_rsp": self.port(
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
            profile=self.link_profile(
                "evict_request",
                ChiChannelKind.REQ,
            ),
        )
        builder.connect_transport(
            "evict_completion",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("hn0", "tx_rsp"),
            VirtualDutPortRef("rn0", "rx_rsp"),
            profile=self.link_profile(
                "evict_completion",
                ChiChannelKind.RSP,
            ),
        )
        claim_name = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                claim_name,
                VirtualDutPortRef("hn0", "rx_req"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        requester = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.REQUESTER,
            self.HOME,
            port_channels={
                "tx_req": frozenset((ChiChannelKind.REQ,)),
                "rx_rsp": frozenset((ChiChannelKind.RSP,)),
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
            ),
            participant_name="requester",
            binding_name="rn0",
        )
        home = self.build_home()
        home_binding = ChiParticipantBinding(
            "hn0",
            duts["hn0"],
            home,
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
            frozenset((self.HOME,)),
        )
        return resolve_chi_system(
            system,
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

    def test_resolved_network_runs_exact_five_packet_witness(self) -> None:
        resolved = self.build_resolved()
        self.assertTrue(resolved.is_closed)
        retry_evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_EVICT_RETRY
        )
        self.assertEqual(
            ("evict_completion",),
            retry_evidence.flows["retry_response"].connections,
        )

        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        initial = session.initial_state()
        issued = self.apply(
            session,
            initial,
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        run = session.run_until_quiescent(
            issued.state,
            max_steps=256,
        )

        self.assertIs(Verdict.PASS, run.verdict)
        self.assertIsNone(run.blocked)
        self.assertTrue(session.is_quiescent(run.final_state))
        endpoint_events = tuple(
            event
            for event in run.emissions
            if event.kind
            is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
        )
        packets = tuple(event.packet for event in endpoint_events)
        self.assertTrue(all(packet is not None for packet in packets))
        self.assertEqual(
            (
                ChiEvictMessage,
                ChiRetryAckMessage,
                ChiPCrdGrantMessage,
                ChiEvictMessage,
                ChiCompMessage,
            ),
            tuple(type(packet.message) for packet in packets),
        )
        initial_request = packets[0].message
        credited_request = packets[3].message
        assert isinstance(initial_request, ChiEvictMessage)
        assert isinstance(credited_request, ChiEvictMessage)
        self.assertTrue(initial_request.allow_retry)
        self.assertFalse(credited_request.allow_retry)
        self.assertEqual(
            self.CREDIT_TYPE,
            credited_request.protocol_credit_type,
        )
        self.assertEqual(
            Counter(
                {
                    ChiChannelKind.REQ: 2,
                    ChiChannelKind.RSP: 3,
                }
            ),
            Counter(packet.channel for packet in packets),
        )
        self.assertFalse(
            any(
                isinstance(
                    packet.message,
                    (
                        ChiSnpUniqueMessage,
                        ChiCompDataMessage,
                        ChiCompAckMessage,
                    ),
                )
                for packet in packets
            )
        )
        final = run.final_state.coherence
        line = final.request_nodes[self.REQUESTER].line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertIsNone(final.home.directory[self.ADDRESS].unique_owner)
        self.assertEqual(initial.coherence.home.backing, final.home.backing)
        self.assertFalse(final.home.request_retry.retry_debts)
        self.assertFalse(final.home.request_retry.reservations)
        self.assertEqual(1, final.home.request_retry.retry_ack_count)
        self.assertEqual(1, final.home.request_retry.grant_count)
        self.assertEqual(1, final.home.request_retry.consumed_count)


if __name__ == "__main__":
    unittest.main()
