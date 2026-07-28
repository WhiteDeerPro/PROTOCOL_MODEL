from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCoherentRnNode,
    ChiHomeDirectoryEntry,
    ChiRnAcceptCompData,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptSnoop,
    ChiRnIssueCleanUnique,
    ChiRnIssueCoherentRead,
    ChiRnIssueWriteBackFull,
    ChiRnWriteBackOutcome,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiIssueHDatProfile,
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiCleanUniqueMessage,
    ChiReadUniqueMessage,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
    ChiRespErr,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiCoherenceState,
    ChiDeliverCoherencePacket,
    ChiSubmitCoherentRead,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHReadUniqueCoherenceTest(unittest.TestCase):
    REQUESTER = 0x07
    FIRST_SHARER = 0x08
    SECOND_SHARER = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xCAFE_BABE

    def build_session(
        self,
        *,
        requester_line: ChiCacheLine | None = None,
        read_unique_nderr_policy=None,
    ) -> ChiCoherenceSession:
        requester = build_chi_cache_participant_fixture(
            "rn_requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(
                () if requester_line is None else (requester_line,)
            ),
        )
        sharers = {
            node_id: build_chi_cache_participant_fixture(
                f"rn_{node_id}",
                node_id,
                self.HOME,
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.SC,
                        self.DATA,
                    ),
                ),
            )
            for node_id in (self.FIRST_SHARER, self.SECOND_SHARER)
        }
        directory_sharers = set(sharers)
        if requester_line is not None:
            directory_sharers.add(self.REQUESTER)
        home = ChiCoherentHomeNode(
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
                    sharers=frozenset(directory_sharers),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
            read_unique_nderr_policy=read_unique_nderr_policy,
        )
        return ChiCoherenceSession(
            "read_unique_clean_sharers",
            home,
            {
                self.REQUESTER: requester,
                **sharers,
            },
            enabled_features=(
                None
                if read_unique_nderr_policy is None
                else frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                        CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
                    )
                )
            ),
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def build_requester(
        self,
        state: ChiCacheState | None,
    ):
        return build_chi_cache_participant_fixture(
            "rn_requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(
                ()
                if state is None
                else (
                    ChiCacheLine(
                        self.ADDRESS,
                        state,
                        self.DATA,
                    ),
                )
            ),
        )

    def snoop_unique_packet(self) -> ChiNetworkPacket:
        return ChiNetworkPacket.snoop(
            ChiSnpUniqueMessage(
                transaction_id=0x100,
                address=self.ADDRESS,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def test_read_unique_invalidates_all_clean_sharers(self) -> None:
        session = self.build_session()
        request = ChiReadUniqueMessage(
            transaction_id=0x12,
            address=self.ADDRESS,
        )

        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        self.assertEqual(
            {self.FIRST_SHARER, self.SECOND_SHARER},
            {packet.target_id for packet in accepted.emissions},
        )
        self.assertTrue(
            all(
                isinstance(packet.message, ChiSnpUniqueMessage)
                and packet.message.do_not_go_to_shared_dirty
                and not packet.message.return_to_source
                for packet in accepted.emissions
            )
        )

        state = accepted.state
        completion = None
        for index, snoop in enumerate(accepted.emissions):
            snooped = self.apply(
                session,
                state,
                ChiDeliverCoherencePacket(snoop),
            )
            self.assertEqual(
                ChiCacheState.I,
                snooped.state.request_nodes[snoop.target_id]
                .lines[self.ADDRESS]
                .state,
            )
            response = snooped.emissions[0]
            self.assertEqual(ChiRespCode.I, response.message.response)
            collected = self.apply(
                session,
                snooped.state,
                ChiDeliverCoherencePacket(response),
            )
            if index == 0:
                self.assertFalse(collected.emissions)
            else:
                completion = collected.emissions[0]
            state = collected.state

        assert completion is not None
        self.assertEqual(ChiRespCode.UC, completion.message.response)
        self.assertEqual(self.DATA, completion.message.data)
        self.assertFalse(
            completion.explain_profile(
                ChiIssueHDatProfile(data_width=512)
            )
        )

        installed = self.apply(
            session,
            state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assertEqual(
            ChiCacheState.UC,
            installed.state.request_nodes[self.REQUESTER]
            .lines[self.ADDRESS]
            .state,
        )
        retired = self.apply(
            session,
            installed.state,
            ChiDeliverCoherencePacket(installed.emissions[0]),
        )

        entry = retired.state.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    def test_sc_read_unique_transient_accepts_same_line_snp_unique(
        self,
    ) -> None:
        requester = self.build_requester(ChiCacheState.SC)
        request = ChiReadUniqueMessage(
            transaction_id=0x12,
            address=self.ADDRESS,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCoherentRead(request),
        )
        retained_pending = issued.state.pending_transactions
        retained_retry = issued.state.request_retry

        snooped = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(self.snoop_unique_packet()),
        )

        invalidated = snooped.state.line_at(self.ADDRESS)
        assert invalidated is not None
        self.assertIs(ChiCacheState.I, invalidated.state)
        self.assertIsNone(invalidated.data)
        self.assertNotIn(self.ADDRESS, snooped.state.cache.lines)
        self.assertEqual(
            retained_pending,
            snooped.state.pending_transactions,
        )
        self.assertEqual(retained_retry, snooped.state.request_retry)
        self.assertEqual(
            {request.transaction_id},
            set(snooped.state.pending_transactions),
        )
        self.assertEqual(
            {request.transaction_id},
            set(snooped.state.request_retry.entries),
        )
        self.assertEqual(1, len(snooped.emissions))
        response = snooped.emissions[0]
        self.assertIsInstance(response.message, ChiSnpRespMessage)
        self.assertIs(ChiRespCode.I, response.message.response)
        self.assertEqual(self.REQUESTER, response.source_id)
        self.assertEqual(self.HOME, response.target_id)

        completed = self.apply(
            requester,
            snooped.state,
            ChiRnAcceptCompData(
                ChiNetworkPacket.data(
                    ChiCompDataMessage(
                        transaction_id=request.transaction_id,
                        data=self.DATA,
                        home_node_id=self.HOME,
                        response=ChiRespCode.UC,
                        data_buffer_id=0x200,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )

        installed = completed.state.line_at(self.ADDRESS)
        assert installed is not None
        self.assertIs(ChiCacheState.UC, installed.state)
        self.assertEqual(self.DATA, installed.data)
        self.assertFalse(completed.state.pending_transactions)
        self.assertFalse(completed.state.request_retry.entries)
        self.assertEqual(1, len(completed.emissions))
        self.assertIsInstance(
            completed.emissions[0].message,
            ChiCompAckMessage,
        )
        self.assertEqual(
            0x200,
            completed.emissions[0].message.transaction_id,
        )

    def test_i_read_unique_transient_accepts_same_line_snp_unique(
        self,
    ) -> None:
        requester = self.build_requester(None)
        request = ChiReadUniqueMessage(
            transaction_id=0x13,
            address=self.ADDRESS,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCoherentRead(request),
        )
        retained_pending = issued.state.pending_transactions
        retained_retry = issued.state.request_retry

        snooped = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(self.snoop_unique_packet()),
        )

        self.assertIsNone(snooped.state.line_at(self.ADDRESS))
        self.assertEqual(
            retained_pending,
            snooped.state.pending_transactions,
        )
        self.assertEqual(retained_retry, snooped.state.request_retry)
        self.assertEqual(1, len(snooped.emissions))
        self.assertIsInstance(
            snooped.emissions[0].message,
            ChiSnpRespMessage,
        )
        self.assertIs(
            ChiRespCode.I,
            snooped.emissions[0].message.response,
        )

    def test_two_pending_read_unique_requests_serialize_via_snoop(
        self,
    ) -> None:
        first = self.build_requester(ChiCacheState.SC)
        second = build_chi_cache_participant_fixture(
            "rn_second_requester",
            self.FIRST_SHARER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    self.DATA,
                ),
            ),
        )
        home = ChiCoherentHomeNode(
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
                    sharers=frozenset(
                        (self.REQUESTER, self.FIRST_SHARER)
                    ),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
        )
        session = ChiCoherenceSession(
            "two_pending_read_unique_requests",
            home,
            {
                self.REQUESTER: first,
                self.FIRST_SHARER: second,
            },
        )
        first_request = ChiReadUniqueMessage(0x20, self.ADDRESS)
        second_request = ChiReadUniqueMessage(0x21, self.ADDRESS)

        first_issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, first_request),
        )
        first_packet = first_issued.emissions[0]
        second_issued = self.apply(
            session,
            first_issued.state,
            ChiSubmitCoherentRead(
                self.FIRST_SHARER,
                second_request,
            ),
        )
        second_packet = second_issued.emissions[0]

        first_accepted = self.apply(
            session,
            second_issued.state,
            ChiDeliverCoherencePacket(first_packet),
        )
        self.assertEqual(1, len(first_accepted.emissions))
        first_snoop = first_accepted.emissions[0]
        self.assertEqual(self.FIRST_SHARER, first_snoop.target_id)

        second_snooped = self.apply(
            session,
            first_accepted.state,
            ChiDeliverCoherencePacket(first_snoop),
        )
        second_state = second_snooped.state.request_nodes[
            self.FIRST_SHARER
        ]
        self.assertIs(
            ChiCacheState.I,
            second_state.line_at(self.ADDRESS).state,
        )
        self.assertEqual(
            {second_request.transaction_id},
            set(second_state.pending_transactions),
        )
        self.assertEqual(
            {second_request.transaction_id},
            set(second_state.request_retry.entries),
        )
        first_completed_at_home = self.apply(
            session,
            second_snooped.state,
            ChiDeliverCoherencePacket(second_snooped.emissions[0]),
        )
        first_installed = self.apply(
            session,
            first_completed_at_home.state,
            ChiDeliverCoherencePacket(
                first_completed_at_home.emissions[0]
            ),
        )
        first_retired = self.apply(
            session,
            first_installed.state,
            ChiDeliverCoherencePacket(first_installed.emissions[0]),
        )
        self.assertFalse(first_retired.state.home.pending)
        self.assertEqual(
            self.REQUESTER,
            first_retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )

        second_accepted = self.apply(
            session,
            first_retired.state,
            ChiDeliverCoherencePacket(second_packet),
        )
        self.assertEqual(1, len(second_accepted.emissions))
        self.assertEqual(
            self.REQUESTER,
            second_accepted.emissions[0].target_id,
        )
        first_snooped = self.apply(
            session,
            second_accepted.state,
            ChiDeliverCoherencePacket(second_accepted.emissions[0]),
        )
        second_completed_at_home = self.apply(
            session,
            first_snooped.state,
            ChiDeliverCoherencePacket(first_snooped.emissions[0]),
        )
        second_installed = self.apply(
            session,
            second_completed_at_home.state,
            ChiDeliverCoherencePacket(
                second_completed_at_home.emissions[0]
            ),
        )
        retired = self.apply(
            session,
            second_installed.state,
            ChiDeliverCoherencePacket(second_installed.emissions[0]),
        )

        first_line = retired.state.request_nodes[
            self.REQUESTER
        ].line_at(self.ADDRESS)
        second_line = retired.state.request_nodes[
            self.FIRST_SHARER
        ].line_at(self.ADDRESS)
        assert first_line is not None
        assert second_line is not None
        self.assertIs(ChiCacheState.I, first_line.state)
        self.assertIs(ChiCacheState.UC, second_line.state)
        self.assertEqual(self.DATA, second_line.data)
        self.assertEqual(
            self.FIRST_SHARER,
            retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    def test_clean_unique_transient_accepts_same_line_snp_unique(
        self,
    ) -> None:
        requester = self.build_requester(ChiCacheState.SC)
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCleanUnique(
                ChiCleanUniqueMessage(0x14, self.ADDRESS)
            ),
        )

        snooped = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(self.snoop_unique_packet()),
        )

        line = snooped.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIn(0x14, snooped.state.pending_transactions)
        self.assertEqual(1, len(snooped.emissions))
        self.assertIsInstance(
            snooped.emissions[0].message,
            ChiSnpRespMessage,
        )
        self.assertIs(
            ChiRespCode.I,
            snooped.emissions[0].message.response,
        )

    def test_writeback_full_transient_cancels_after_same_line_snp_unique(
        self,
    ) -> None:
        requester = self.build_requester(ChiCacheState.UD)
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueWriteBackFull(
                ChiWriteBackFullMessage(0x15, self.ADDRESS)
            ),
        )

        snooped = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(self.snoop_unique_packet()),
        )

        line = snooped.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        pending = snooped.state.pending_writebacks[0x15]
        self.assertIs(
            ChiRnWriteBackOutcome.CANCELED_I,
            pending.outcome,
        )
        response = snooped.emissions[0]
        self.assertIsInstance(response.message, ChiSnpRespDataMessage)
        self.assertIs(ChiRespCode.I_PD, response.message.response)
        self.assertEqual(self.DATA, response.message.data)

        repeated = self.apply(
            requester,
            snooped.state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpUniqueMessage(
                        transaction_id=0x101,
                        address=self.ADDRESS,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        repeated_response = repeated.emissions[0].message
        self.assertIsInstance(repeated_response, ChiSnpRespMessage)
        self.assertIs(ChiRespCode.I, repeated_response.response)
        self.assertIs(
            ChiRnWriteBackOutcome.CANCELED_I,
            repeated.state.pending_writebacks[0x15].outcome,
        )

        completed = self.apply(
            requester,
            repeated.state,
            ChiRnAcceptCompDBIDResp(
                ChiNetworkPacket.response(
                    ChiCompDBIDRespMessage(
                        transaction_id=0x15,
                        data_buffer_id=0x200,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        self.assertFalse(completed.state.pending_writebacks)
        copyback = completed.emissions[0].message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertIs(ChiRespCode.I, copyback.response)
        self.assertEqual(0, copyback.data)
        self.assertEqual(0, copyback.byte_enable)

    def _assert_read_unique_nderr_lifecycle(
        self,
        requester_line: ChiCacheLine | None,
    ) -> None:
        session = self.build_session(
            requester_line=requester_line,
            read_unique_nderr_policy=lambda _request, _state: True,
        )
        initial = session.initial_state()
        initial_requester = initial.request_nodes[self.REQUESTER]
        initial_peers = {
            node_id: initial.request_nodes[node_id]
            for node_id in (self.FIRST_SHARER, self.SECOND_SHARER)
        }
        initial_directory = initial.home.directory
        initial_backing = initial.home.backing
        initial_snoop_id = initial.home.next_snoop_transaction_id
        request = ChiReadUniqueMessage(
            transaction_id=0x12,
            address=self.ADDRESS,
        )

        issued = self.apply(
            session,
            initial,
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        self.assertEqual(1, len(accepted.emissions))
        completion = accepted.emissions[0]
        self.assertIsInstance(completion.message, ChiCompDataMessage)
        self.assertIs(ChiRespErr.NDERR, completion.message.response_error)
        self.assertEqual(ChiRespCode.I, completion.message.response)
        self.assertEqual(0, completion.message.data)
        self.assertEqual(0, completion.message.data_id)
        self.assertEqual(0x200, completion.message.data_buffer_id)
        completion_key = (self.REQUESTER, request.transaction_id)
        self.assertEqual(
            completion,
            accepted.state.expected_coherent_read_completions[
                completion_key
            ],
        )
        self.assertEqual(initial_directory, accepted.state.home.directory)
        self.assertEqual(initial_backing, accepted.state.home.backing)
        self.assertEqual(
            initial_snoop_id,
            accepted.state.home.next_snoop_transaction_id,
        )
        pending = accepted.state.home.pending[0x200]
        self.assertIsNone(pending.snoop_transaction_id)
        self.assertFalse(pending.snoop_targets)
        self.assertFalse(pending.snoop_results)
        self.assertTrue(pending.completion_sent)
        self.assertIs(
            ChiRespErr.NDERR,
            pending.completion_response_error,
        )
        self.assertIsNone(pending.prepared_backing_write)
        for node_id, peer in initial_peers.items():
            self.assertEqual(peer, accepted.state.request_nodes[node_id])

        early_ack = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiCompAckMessage(transaction_id=0x200),
                    source_id=self.REQUESTER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assertIsNotNone(early_ack.fault)
        assert early_ack.fault is not None
        self.assertTrue(
            early_ack.fault.rule.endswith(
                "coherent_read_completion_ack_sequence"
            )
        )
        self.assertIs(accepted.state, early_ack.state)

        contender_issued = self.apply(
            session,
            accepted.state,
            ChiSubmitCoherentRead(
                self.FIRST_SHARER,
                ChiReadUniqueMessage(
                    transaction_id=0x13,
                    address=self.ADDRESS,
                ),
            ),
        )
        contended = session.step(
            contender_issued.state,
            ChiDeliverCoherencePacket(contender_issued.emissions[0]),
        )
        self.assertIsNone(contended.fault)
        self.assertIsNotNone(contended.blocked)
        assert contended.blocked is not None
        self.assertIn("same-line", contended.blocked.reason)
        self.assertEqual(accepted.state.home, contended.state.home)

        completed = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assertFalse(
            completed.state.expected_coherent_read_completions
        )
        requester = completed.state.request_nodes[self.REQUESTER]
        self.assertEqual(initial_requester.cache, requester.cache)
        self.assertEqual(
            initial_requester.permissions,
            requester.permissions,
        )
        self.assertFalse(requester.pending_transactions)
        self.assertFalse(requester.request_retry.entries)
        self.assertEqual(accepted.state.home, completed.state.home)
        self.assertEqual(1, len(completed.emissions))
        ack = completed.emissions[0]
        self.assertIsInstance(ack.message, ChiCompAckMessage)
        self.assertEqual(0x200, ack.message.transaction_id)
        self.assertEqual(self.REQUESTER, ack.source_id)
        self.assertEqual(self.HOME, ack.target_id)

        retired = self.apply(
            session,
            completed.state,
            ChiDeliverCoherencePacket(ack),
        )
        self.assertFalse(retired.state.home.pending)
        self.assertEqual(initial_directory, retired.state.home.directory)
        self.assertEqual(initial_backing, retired.state.home.backing)
        self.assertEqual(
            initial_snoop_id,
            retired.state.home.next_snoop_transaction_id,
        )
        requester = retired.state.request_nodes[self.REQUESTER]
        self.assertEqual(initial_requester.cache, requester.cache)
        self.assertEqual(
            initial_requester.permissions,
            requester.permissions,
        )
        for node_id, peer in initial_peers.items():
            self.assertEqual(peer, retired.state.request_nodes[node_id])
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    def test_read_unique_nderr_from_i_does_not_install_a_line(self) -> None:
        self._assert_read_unique_nderr_lifecycle(None)

    def test_read_unique_nderr_from_sc_preserves_requester_and_peers(
        self,
    ) -> None:
        self._assert_read_unique_nderr_lifecycle(
            ChiCacheLine(
                self.ADDRESS,
                ChiCacheState.SC,
                self.DATA,
            )
        )

    def test_nderr_policy_false_keeps_the_normal_snoop_path(self) -> None:
        session = self.build_session(
            read_unique_nderr_policy=lambda _request, _state: False,
        )
        request = ChiReadUniqueMessage(
            transaction_id=0x14,
            address=self.ADDRESS,
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        self.assertEqual(2, len(accepted.emissions))
        self.assertTrue(
            all(
                isinstance(packet.message, ChiSnpUniqueMessage)
                for packet in accepted.emissions
            )
        )
        pending = accepted.state.home.pending[0x200]
        self.assertEqual(0x100, pending.snoop_transaction_id)
        self.assertIs(
            ChiRespErr.OK,
            pending.completion_response_error,
        )

    def test_base_feature_rejects_forged_nderr_without_state_change(
        self,
    ) -> None:
        session = self.build_session()
        request = ChiReadUniqueMessage(
            transaction_id=0x15,
            address=self.ADDRESS,
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        forged = ChiNetworkPacket.data(
            ChiCompDataMessage(
                transaction_id=request.transaction_id,
                data=0,
                home_node_id=self.HOME,
                response_error=ChiRespErr.NDERR,
                response=ChiRespCode.I,
                data_buffer_id=0x205,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

        rejected = session.step(
            issued.state,
            ChiDeliverCoherencePacket(forged),
        )

        self.assertIsNotNone(rejected.fault)
        assert rejected.fault is not None
        self.assertIn("not enabled", rejected.fault.reason)
        self.assertIs(issued.state, rejected.state)
        self.assertIn(
            request.transaction_id,
            rejected.state.request_nodes[
                self.REQUESTER
            ].pending_transactions,
        )

    def test_nderr_completion_must_match_home_dbid_and_error_kind(
        self,
    ) -> None:
        session = self.build_session(
            read_unique_nderr_policy=lambda _request, _state: True,
        )
        request = ChiReadUniqueMessage(
            transaction_id=0x16,
            address=self.ADDRESS,
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        completion = accepted.emissions[0]
        self.assertEqual(
            completion,
            accepted.state.expected_coherent_read_completions[
                (self.REQUESTER, request.transaction_id)
            ],
        )
        cases = (
            ChiNetworkPacket.data(
                ChiCompDataMessage(
                    transaction_id=request.transaction_id,
                    data=0,
                    home_node_id=self.HOME,
                    response_error=ChiRespErr.NDERR,
                    response=ChiRespCode.I,
                    data_buffer_id=0x201,
                ),
                source_id=self.HOME,
                target_id=self.REQUESTER,
            ),
            ChiNetworkPacket.data(
                ChiCompDataMessage(
                    transaction_id=request.transaction_id,
                    data=self.DATA,
                    home_node_id=self.HOME,
                    response_error=ChiRespErr.OK,
                    response=ChiRespCode.UC,
                    data_buffer_id=0x200,
                ),
                source_id=self.HOME,
                target_id=self.REQUESTER,
            ),
            replace(
                completion,
                packet_index=1,
                packet_count=2,
            ),
        )

        for forged in cases:
            with self.subTest(
                data_buffer_id=forged.message.data_buffer_id,
                response_error=forged.message.response_error,
                packet_index=forged.packet_index,
                packet_count=forged.packet_count,
            ):
                rejected = session.step(
                    accepted.state,
                    ChiDeliverCoherencePacket(forged),
                )

                self.assertIsNotNone(rejected.fault)
                assert rejected.fault is not None
                self.assertIn(
                    "Requester/TxnID/DBID/RespErr",
                    rejected.fault.reason,
                )
                self.assertIs(accepted.state, rejected.state)
                self.assertIn(0x200, rejected.state.home.pending)
                self.assertIn(
                    request.transaction_id,
                    rejected.state.request_nodes[
                        self.REQUESTER
                    ].pending_transactions,
                )

    def test_completed_home_read_requires_expected_packet_evidence(
        self,
    ) -> None:
        session = self.build_session(
            read_unique_nderr_policy=lambda _request, _state: True,
        )
        request = ChiReadUniqueMessage(0x17, self.ADDRESS)
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires exactly one expected CompData",
        ):
            ChiCoherenceState(
                home=accepted.state.home,
                request_nodes=accepted.state.request_nodes,
                expected_evict_completions=(
                    accepted.state.expected_evict_completions
                ),
                expected_clean_unique_completions=(
                    accepted.state.expected_clean_unique_completions
                ),
                expected_make_unique_completions=(
                    accepted.state.expected_make_unique_completions
                ),
                expected_snoop_deliveries=(
                    accepted.state.expected_snoop_deliveries
                ),
                expected_snoop_responses=(
                    accepted.state.expected_snoop_responses
                ),
            )

    def test_nderr_policy_and_feature_must_be_enabled_together(self) -> None:
        configured = self.build_session(
            read_unique_nderr_policy=lambda _request, _state: True,
        )
        with self.assertRaisesRegex(
            ValueError,
            "NDERR policy requires",
        ):
            ChiCoherenceSession(
                "missing_nderr_feature",
                configured.home,
                configured.request_nodes,
                enabled_features=frozenset(
                    (CHI_FEATURE_CLEAN_READ_UNIQUE,)
                ),
            )

        base = self.build_session()
        with self.assertRaisesRegex(
            ValueError,
            "feature requires a configured",
        ):
            ChiCoherenceSession(
                "missing_nderr_policy",
                base.home,
                base.request_nodes,
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                        CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
                    )
                ),
            )
    def test_session_rejects_ambiguous_participant_names(self) -> None:
        base = self.build_session()

        for duplicate_name in (
            base.home.name,
            base.request_nodes[self.REQUESTER].name,
        ):
            with self.subTest(duplicate_name=duplicate_name):
                template = base.request_nodes[self.REQUESTER]
                duplicate = ChiCoherentRnNode(
                    duplicate_name,
                    0x0A,
                    self.HOME,
                    cache_core=template.cache_core,
                    initial_permissions=template.initial_permissions,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "participant names must be unique",
                ):
                    ChiCoherenceSession(
                        "ambiguous_participant_names",
                        base.home,
                        {
                            **base.request_nodes,
                            duplicate.node_id: duplicate,
                        },
                    )

    def test_session_rejects_an_orphan_data_return_snoop(
        self,
    ) -> None:
        session = self.build_session()
        packet = ChiNetworkPacket.snoop(
            ChiSnpUniqueMessage(
                transaction_id=1,
                address=self.ADDRESS,
                return_to_source=True,
            ),
            source_id=self.HOME,
            target_id=self.FIRST_SHARER,
        )

        transition = session.step(
            session.initial_state(),
            ChiDeliverCoherencePacket(packet),
        )

        self.assertIsNotNone(transition.fault)
        self.assertIn("Home-issued target", transition.fault.reason)


if __name__ == "__main__":
    unittest.main()
