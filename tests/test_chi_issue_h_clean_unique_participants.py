from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCoherentHomeState,
    ChiHomeAcceptCleanUnique,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptSnoopResponse,
    ChiHomeDirectoryEntry,
    ChiRnAcceptComp,
    ChiRnAcceptSnoop,
    ChiRnIssueCleanUnique,
    ChiRnWriteCacheLine,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiCleanUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompAckMessage,
    ChiCompMessage,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpCleanInvalidMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitCleanUnique,
    ChiWriteUniqueCacheLine,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHCleanUniqueParticipantTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    CLEAN_PEER = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC1EA
    DIRTY_DATA = (1 << 401) | 0xD17A
    TXN_ID = 0x12
    SNOOP_ID = 0x100
    DBID = 0x200

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

    def build_rn(
        self,
        name: str,
        node_id: int,
        state: ChiCacheState,
        *,
        data: int | None = None,
    ):
        return build_chi_cache_participant_fixture(
            name,
            node_id,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    state,
                    (
                        None
                        if state in (ChiCacheState.I, ChiCacheState.UCE)
                        else self.DATA if data is None else data
                    ),
                ),
            ),
        )

    def build_home(
        self,
        *,
        sharers: frozenset[int],
        unique_owner: int | None = None,
        shared_dirty_owner: int | None = None,
        allow_dirty_data_transfer: bool = False,
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
                    sharers=sharers,
                    unique_owner=unique_owner,
                    shared_dirty_owner=shared_dirty_owner,
                ),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
            allow_dirty_data_transfer=allow_dirty_data_transfer,
        )

    def request(self) -> ChiCleanUniqueMessage:
        return ChiCleanUniqueMessage(self.TXN_ID, self.ADDRESS)

    def request_packet(self) -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            self.request(),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )

    def test_clean_unique_runs_the_dataless_five_packet_lifecycle(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.SC,
        )
        peer = self.build_rn("peer", self.PEER, ChiCacheState.SC)
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER))
        )
        requester_state = requester.initial_state()
        peer_state = peer.initial_state()
        home_state = home.initial_state()

        issued = self.apply(
            requester,
            requester_state,
            ChiRnIssueCleanUnique(self.request()),
        )
        request_packet = issued.emissions[0]
        self.assertIsInstance(
            request_packet.message,
            ChiCleanUniqueMessage,
        )
        self.assertEqual(
            {self.TXN_ID},
            set(issued.state.pending_transactions),
        )
        self.assertIs(
            ChiCacheState.SC,
            issued.state.line_at(self.ADDRESS).state,
        )

        accepted = self.apply(
            home,
            home_state,
            ChiHomeAcceptCleanUnique(request_packet),
        )
        self.assertEqual({self.DBID}, set(accepted.state.pending))
        pending = accepted.state.pending[self.DBID]
        self.assertEqual(self.REQUESTER, pending.requester_id)
        self.assertEqual(self.SNOOP_ID, pending.snoop_transaction_id)
        self.assertFalse(pending.completion_sent)
        self.assertEqual(
            home_state.directory,
            accepted.state.directory,
        )
        self.assertEqual(1, len(accepted.emissions))
        snoop_packet = accepted.emissions[0]
        self.assertEqual(self.PEER, snoop_packet.target_id)
        self.assertIsInstance(
            snoop_packet.message,
            ChiSnpCleanInvalidMessage,
        )
        self.assertTrue(
            snoop_packet.message.do_not_go_to_shared_dirty
        )
        self.assertFalse(snoop_packet.message.return_to_source)

        snooped = self.apply(
            peer,
            peer_state,
            ChiRnAcceptSnoop(snoop_packet),
        )
        self.assertIs(
            ChiCacheState.I,
            snooped.state.line_at(self.ADDRESS).state,
        )
        snoop_response = snooped.emissions[0]
        self.assertIsInstance(
            snoop_response.message,
            ChiSnpRespMessage,
        )
        self.assertIs(ChiRespCode.I, snoop_response.message.response)

        collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(snoop_response),
        )
        completion_packet = collected.emissions[0]
        self.assertIsInstance(
            completion_packet.message,
            ChiCompMessage,
        )
        self.assertEqual(
            self.TXN_ID,
            completion_packet.message.transaction_id,
        )
        self.assertEqual(
            self.DBID,
            completion_packet.message.data_buffer_id,
        )
        self.assertIs(
            ChiRespCode.UC,
            completion_packet.message.response,
        )
        self.assertTrue(
            collected.state.pending[self.DBID].completion_sent
        )
        self.assertIsNone(
            collected.state.pending[
                self.DBID
            ].prepared_backing_write
        )
        self.assertEqual(
            home_state.directory,
            collected.state.directory,
        )

        installed = self.apply(
            requester,
            issued.state,
            ChiRnAcceptComp(completion_packet),
        )
        requester_line = installed.state.line_at(self.ADDRESS)
        self.assertIs(ChiCacheState.UC, requester_line.state)
        self.assertEqual(self.DATA, requester_line.data)
        self.assertFalse(installed.state.pending_transactions)
        completion_ack = installed.emissions[0]
        self.assertIsInstance(
            completion_ack.message,
            ChiCompAckMessage,
        )
        self.assertEqual(
            self.DBID,
            completion_ack.message.transaction_id,
        )

        retired = self.apply(
            home,
            collected.state,
            ChiHomeAcceptCompAck(completion_ack),
        )
        entry = retired.state.directory[self.ADDRESS]
        self.assertEqual(
            self.DATA,
            retired.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(
            0,
            retired.state.backing.line_at(self.ADDRESS).version,
        )
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertTrue(requester.is_quiescent(installed.state))
        self.assertTrue(home.is_quiescent(retired.state))

    def test_pending_clean_unique_accepts_invalidating_snoops_and_completes_uce(
        self,
    ) -> None:
        for snoop_message, returns_data in (
            (
                ChiSnpUniqueMessage(
                    self.SNOOP_ID,
                    self.ADDRESS,
                    return_to_source=False,
                ),
                False,
            ),
            (
                ChiSnpUniqueMessage(
                    self.SNOOP_ID,
                    self.ADDRESS,
                    return_to_source=True,
                ),
                True,
            ),
            (
                ChiSnpCleanInvalidMessage(
                    self.SNOOP_ID,
                    self.ADDRESS,
                ),
                False,
            ),
        ):
            with self.subTest(
                snoop=type(snoop_message).__name__,
                returns_data=returns_data,
            ):
                requester = self.build_rn(
                    "requester",
                    self.REQUESTER,
                    ChiCacheState.SC,
                )
                issued = self.apply(
                    requester,
                    requester.initial_state(),
                    ChiRnIssueCleanUnique(self.request()),
                )
                snooped = self.apply(
                    requester,
                    issued.state,
                    ChiRnAcceptSnoop(
                        ChiNetworkPacket.snoop(
                            snoop_message,
                            source_id=self.HOME,
                            target_id=self.REQUESTER,
                        )
                    ),
                )

                line = snooped.state.line_at(self.ADDRESS)
                assert line is not None
                self.assertIs(ChiCacheState.I, line.state)
                self.assertIsNone(line.data)
                self.assertNotIn(self.ADDRESS, snooped.state.cache.lines)
                self.assertIn(
                    self.TXN_ID,
                    snooped.state.pending_transactions,
                )
                response = snooped.emissions[0]
                self.assertIsInstance(
                    response.message,
                    (
                        ChiSnpRespDataMessage
                        if returns_data
                        else ChiSnpRespMessage
                    ),
                )
                self.assertIs(ChiRespCode.I, response.message.response)
                if returns_data:
                    self.assertEqual(self.DATA, response.message.data)

                completed = self.apply(
                    requester,
                    snooped.state,
                    ChiRnAcceptComp(
                        ChiNetworkPacket.response(
                            ChiCompMessage(
                                transaction_id=self.TXN_ID,
                                data_buffer_id=self.DBID,
                                response=ChiRespCode.UC,
                            ),
                            source_id=self.HOME,
                            target_id=self.REQUESTER,
                        )
                    ),
                )
                line = completed.state.line_at(self.ADDRESS)
                assert line is not None
                self.assertIs(ChiCacheState.UCE, line.state)
                self.assertIsNone(line.data)
                self.assertNotIn(self.ADDRESS, completed.state.cache.lines)
                self.assertFalse(completed.state.pending_transactions)
                self.assertIsInstance(
                    completed.emissions[0].message,
                    ChiCompAckMessage,
                )

                written = self.apply(
                    requester,
                    completed.state,
                    ChiRnWriteCacheLine(
                        self.ADDRESS,
                        self.DIRTY_DATA,
                    ),
                )
                line = written.state.line_at(self.ADDRESS)
                assert line is not None
                self.assertIs(ChiCacheState.UD, line.state)
                self.assertEqual(self.DIRTY_DATA, line.data)

    def test_clean_unique_from_i_completes_uce(self) -> None:
        requester = self.build_rn(
            "invalid_requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCleanUnique(self.request()),
        )

        initial_line = issued.state.line_at(self.ADDRESS)
        assert initial_line is not None
        self.assertIs(ChiCacheState.I, initial_line.state)
        self.assertIsNone(initial_line.data)
        self.assertNotIn(self.ADDRESS, issued.state.cache.lines)

        completed = self.apply(
            requester,
            issued.state,
            ChiRnAcceptComp(
                ChiNetworkPacket.response(
                    ChiCompMessage(
                        transaction_id=self.TXN_ID,
                        data_buffer_id=self.DBID,
                        response=ChiRespCode.UC,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )

        line = completed.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.UCE, line.state)
        self.assertIsNone(line.data)
        self.assertFalse(completed.state.pending_transactions)

    def test_uce_snp_unique_with_return_to_source_has_no_data(
        self,
    ) -> None:
        requester = self.build_rn(
            "empty_unique",
            self.REQUESTER,
            ChiCacheState.UCE,
        )
        initial = requester.initial_state()
        self.assertNotIn(self.ADDRESS, initial.cache.lines)

        snooped = self.apply(
            requester,
            initial,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpUniqueMessage(
                        self.SNOOP_ID,
                        self.ADDRESS,
                        return_to_source=True,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )

        line = snooped.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertIsInstance(
            snooped.emissions[0].message,
            ChiSnpRespMessage,
        )
        self.assertIs(
            ChiRespCode.I,
            snooped.emissions[0].message.response,
        )

    def test_uce_rejects_payload_storage(self) -> None:
        with self.assertRaises(ValueError):
            ChiCacheLine(
                self.ADDRESS,
                ChiCacheState.UCE,
                self.DATA,
            )

    def test_two_pending_clean_unique_requests_serialize_through_uce(
        self,
    ) -> None:
        first = self.build_rn(
            "first",
            self.REQUESTER,
            ChiCacheState.SC,
        )
        second = self.build_rn(
            "second",
            self.PEER,
            ChiCacheState.SC,
        )
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER))
        )
        session = ChiCoherenceSession(
            "two_clean_unique",
            home,
            {
                self.REQUESTER: first,
                self.PEER: second,
            },
            enabled_features=frozenset(
                (CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,)
            ),
        )
        state = session.initial_state()

        first_issued = self.apply(
            session,
            state,
            ChiSubmitCleanUnique(
                self.REQUESTER,
                ChiCleanUniqueMessage(0x31, self.ADDRESS),
            ),
        )
        second_issued = self.apply(
            session,
            first_issued.state,
            ChiSubmitCleanUnique(
                self.PEER,
                ChiCleanUniqueMessage(0x32, self.ADDRESS),
            ),
        )
        first_at_home = self.apply(
            session,
            second_issued.state,
            ChiDeliverCoherencePacket(first_issued.emissions[0]),
        )
        second_snooped = self.apply(
            session,
            first_at_home.state,
            ChiDeliverCoherencePacket(first_at_home.emissions[0]),
        )
        first_completed_at_home = self.apply(
            session,
            second_snooped.state,
            ChiDeliverCoherencePacket(second_snooped.emissions[0]),
        )
        first_completed = self.apply(
            session,
            first_completed_at_home.state,
            ChiDeliverCoherencePacket(
                first_completed_at_home.emissions[0]
            ),
        )
        first_retired = self.apply(
            session,
            first_completed.state,
            ChiDeliverCoherencePacket(first_completed.emissions[0]),
        )

        second_at_home = self.apply(
            session,
            first_retired.state,
            ChiDeliverCoherencePacket(second_issued.emissions[0]),
        )
        first_snooped = self.apply(
            session,
            second_at_home.state,
            ChiDeliverCoherencePacket(second_at_home.emissions[0]),
        )
        second_completed_at_home = self.apply(
            session,
            first_snooped.state,
            ChiDeliverCoherencePacket(first_snooped.emissions[0]),
        )
        second_completed = self.apply(
            session,
            second_completed_at_home.state,
            ChiDeliverCoherencePacket(
                second_completed_at_home.emissions[0]
            ),
        )
        retired = self.apply(
            session,
            second_completed.state,
            ChiDeliverCoherencePacket(second_completed.emissions[0]),
        )

        first_line = retired.state.request_nodes[
            self.REQUESTER
        ].line_at(self.ADDRESS)
        second_line = retired.state.request_nodes[
            self.PEER
        ].line_at(self.ADDRESS)
        assert first_line is not None
        assert second_line is not None
        self.assertIs(ChiCacheState.I, first_line.state)
        self.assertIs(ChiCacheState.UCE, second_line.state)
        self.assertIsNone(second_line.data)
        self.assertNotIn(
            self.ADDRESS,
            retired.state.request_nodes[self.PEER].cache.lines,
        )
        self.assertEqual(
            self.PEER,
            retired.state.home.directory[self.ADDRESS].unique_owner,
        )
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

        written = self.apply(
            session,
            retired.state,
            ChiWriteUniqueCacheLine(
                self.PEER,
                self.ADDRESS,
                self.DIRTY_DATA,
            ),
        )
        written_line = written.state.request_nodes[
            self.PEER
        ].line_at(self.ADDRESS)
        assert written_line is not None
        self.assertIs(ChiCacheState.UD, written_line.state)
        self.assertEqual(self.DIRTY_DATA, written_line.data)
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                written.state.home,
                written.state.request_nodes,
            )
        )

    def test_clean_unique_rejects_a_dirty_requester_without_mutation(
        self,
    ) -> None:
        requester = self.build_rn(
            "dirty_requester",
            self.REQUESTER,
            ChiCacheState.UD,
        )
        state = requester.initial_state()

        transition = requester.step(
            state,
            ChiRnIssueCleanUnique(self.request()),
        )

        self.assert_fault_rule(
            transition,
            "clean_unique_dirty_requester",
        )
        self.assertEqual(state, transition.state)
        self.assertFalse(transition.emissions)

    def test_snp_clean_invalid_returns_shared_dirty_data_and_invalidates_peer(
        self,
    ) -> None:
        peer = self.build_rn(
            "shared_dirty_peer",
            self.PEER,
            ChiCacheState.SD,
            data=self.DIRTY_DATA,
        )
        state = peer.initial_state()
        snoop = ChiNetworkPacket.snoop(
            ChiSnpCleanInvalidMessage(self.SNOOP_ID, self.ADDRESS),
            source_id=self.HOME,
            target_id=self.PEER,
        )

        transition = self.apply(peer, state, ChiRnAcceptSnoop(snoop))

        self.assertIs(
            ChiCacheState.I,
            transition.state.line_at(self.ADDRESS).state,
        )
        self.assertNotIn(self.ADDRESS, transition.state.cache.lines)
        self.assertEqual(1, len(transition.emissions))
        response = transition.emissions[0]
        self.assertIsInstance(response.message, ChiSnpRespDataMessage)
        self.assertIs(ChiRespCode.I_PD, response.message.response)
        self.assertEqual(self.DIRTY_DATA, response.message.data)
        self.assertEqual(self.SNOOP_ID, response.message.transaction_id)
        self.assertEqual(self.PEER, response.source_id)
        self.assertEqual(self.HOME, response.target_id)

    def test_home_commits_shared_dirty_data_and_unique_authority_atomically(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER)),
            shared_dirty_owner=self.PEER,
            allow_dirty_data_transfer=True,
        )
        initial = home.initial_state()
        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )
        snoop = accepted.emissions[0]
        dirty_response = ChiNetworkPacket.data(
            ChiSnpRespDataMessage(
                transaction_id=snoop.message.transaction_id,
                data=self.DIRTY_DATA,
                response=ChiRespCode.I_PD,
            ),
            source_id=self.PEER,
            target_id=self.HOME,
        )

        collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(dirty_response),
        )

        before_ack = collected.state.directory[self.ADDRESS]
        self.assertEqual(
            self.DATA,
            collected.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(
            0,
            collected.state.backing.line_at(self.ADDRESS).version,
        )
        self.assertEqual(
            frozenset((self.REQUESTER, self.PEER)),
            before_ack.sharers,
        )
        self.assertEqual(self.PEER, before_ack.shared_dirty_owner)
        self.assertIsNone(before_ack.unique_owner)
        pending = collected.state.pending[self.DBID]
        self.assertEqual(self.DIRTY_DATA, pending.dirty_result.data)
        self.assertEqual(self.DIRTY_DATA, pending.memory_update_data)
        self.assertIsNotNone(pending.prepared_backing_write)
        prepared = pending.prepared_backing_write
        assert prepared is not None
        self.assertEqual(
            0,
            prepared.expected_version,
        )
        completion = collected.emissions[0]
        self.assertIsInstance(completion.message, ChiCompMessage)
        self.assertIs(ChiRespCode.UC, completion.message.response)

        ack = ChiNetworkPacket.response(
            ChiCompAckMessage(transaction_id=self.DBID),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )
        retired = self.apply(
            home,
            collected.state,
            ChiHomeAcceptCompAck(ack),
        )

        entry = retired.state.directory[self.ADDRESS]
        self.assertEqual(
            self.DIRTY_DATA,
            retired.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(
            1,
            retired.state.backing.line_at(self.ADDRESS).version,
        )
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        self.assertFalse(retired.state.pending)

    def test_home_absorbs_dirty_unique_owner_before_clean_unique_grant(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset(),
            unique_owner=self.PEER,
            allow_dirty_data_transfer=True,
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )
        snoop = accepted.emissions[0]
        self.assertEqual(self.PEER, snoop.target_id)

        collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(
                ChiNetworkPacket.data(
                    ChiSnpRespDataMessage(
                        transaction_id=snoop.message.transaction_id,
                        data=self.DIRTY_DATA,
                        response=ChiRespCode.I_PD,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assertIsNotNone(
            collected.state.pending[self.DBID].prepared_backing_write
        )

        retired = self.apply(
            home,
            collected.state,
            ChiHomeAcceptCompAck(
                ChiNetworkPacket.response(
                    ChiCompAckMessage(transaction_id=self.DBID),
                    source_id=self.REQUESTER,
                    target_id=self.HOME,
                )
            ),
        )
        entry = retired.state.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertEqual(
            self.DIRTY_DATA,
            retired.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(
            1,
            retired.state.backing.line_at(self.ADDRESS).version,
        )

    def test_stale_prepared_backing_write_preserves_directory_and_pending(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER)),
            shared_dirty_owner=self.PEER,
            allow_dirty_data_transfer=True,
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )
        collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(
                ChiNetworkPacket.data(
                    ChiSnpRespDataMessage(
                        transaction_id=self.SNOOP_ID,
                        data=self.DIRTY_DATA,
                        response=ChiRespCode.I_PD,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        competing = home.backing_core.prepare_write(
            collected.state.backing,
            self.ADDRESS,
            self.DATA ^ 1,
        )
        changed_backing = home.backing_core.commit_write(
            collected.state.backing,
            competing,
        ).state
        conflicting_state = ChiCoherentHomeState(
            directory=collected.state.directory,
            backing=changed_backing,
            pending=collected.state.pending,
            next_snoop_transaction_id=(
                collected.state.next_snoop_transaction_id
            ),
            next_data_buffer_id=collected.state.next_data_buffer_id,
            pending_writebacks=collected.state.pending_writebacks,
        )
        ack = ChiNetworkPacket.response(
            ChiCompAckMessage(transaction_id=self.DBID),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )

        rejected = home.step(
            conflicting_state,
            ChiHomeAcceptCompAck(ack),
        )

        self.assert_fault_rule(rejected, "backing_commit_conflict")
        self.assertIs(conflicting_state, rejected.state)
        self.assertIn(self.DBID, rejected.state.pending)
        entry = rejected.state.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertEqual(self.PEER, entry.shared_dirty_owner)
        self.assertEqual(
            self.DATA ^ 1,
            rejected.state.backing.line_at(self.ADDRESS).data,
        )

    def test_home_collects_mixed_clean_rsp_and_shared_dirty_dat(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset(
                (self.REQUESTER, self.PEER, self.CLEAN_PEER)
            ),
            shared_dirty_owner=self.PEER,
            allow_dirty_data_transfer=True,
        )
        initial = home.initial_state()
        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )
        self.assertEqual(
            {self.PEER, self.CLEAN_PEER},
            {packet.target_id for packet in accepted.emissions},
        )

        clean_response = ChiNetworkPacket.response(
            ChiSnpRespMessage(
                transaction_id=self.SNOOP_ID,
                response=ChiRespCode.I,
            ),
            source_id=self.CLEAN_PEER,
            target_id=self.HOME,
        )
        clean_collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(clean_response),
        )
        self.assertFalse(clean_collected.emissions)
        self.assertEqual(initial.directory, clean_collected.state.directory)

        dirty_response = ChiNetworkPacket.data(
            ChiSnpRespDataMessage(
                transaction_id=self.SNOOP_ID,
                data=self.DIRTY_DATA,
                response=ChiRespCode.I_PD,
            ),
            source_id=self.PEER,
            target_id=self.HOME,
        )
        all_collected = self.apply(
            home,
            clean_collected.state,
            ChiHomeAcceptSnoopResponse(dirty_response),
        )

        self.assertEqual(1, len(all_collected.emissions))
        self.assertIsInstance(
            all_collected.emissions[0].message,
            ChiCompMessage,
        )
        pending = all_collected.state.pending[self.DBID]
        self.assertTrue(pending.completion_sent)
        self.assertEqual(
            {self.PEER, self.CLEAN_PEER},
            set(pending.snoop_results),
        )
        self.assertEqual(self.DIRTY_DATA, pending.dirty_result.data)
        self.assertEqual(self.DIRTY_DATA, pending.memory_update_data)
        self.assertEqual(initial.directory, all_collected.state.directory)

    def test_home_rejects_a_second_pass_dirty_source_without_mutation(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset(
                (self.REQUESTER, self.PEER, self.CLEAN_PEER)
            ),
            shared_dirty_owner=self.PEER,
            allow_dirty_data_transfer=True,
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )

        def dirty_packet(source_id: int, data: int) -> ChiNetworkPacket:
            return ChiNetworkPacket.data(
                ChiSnpRespDataMessage(
                    transaction_id=self.SNOOP_ID,
                    data=data,
                    response=ChiRespCode.I_PD,
                ),
                source_id=source_id,
                target_id=self.HOME,
            )

        first = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(
                dirty_packet(self.PEER, self.DIRTY_DATA)
            ),
        )
        second = home.step(
            first.state,
            ChiHomeAcceptSnoopResponse(
                dirty_packet(self.CLEAN_PEER, self.DIRTY_DATA + 1)
            ),
        )

        self.assertIsNotNone(second.fault)
        self.assertIn("dirty", second.fault.reason.lower())
        self.assertEqual(first.state, second.state)
        self.assertFalse(second.emissions)

    def test_shared_dirty_owner_must_be_one_non_unique_sharer(self) -> None:
        with self.assertRaises(ValueError):
            ChiHomeDirectoryEntry(
                self.ADDRESS,
                sharers=frozenset((self.REQUESTER,)),
                shared_dirty_owner=self.PEER,
            )
        with self.assertRaises(ValueError):
            ChiHomeDirectoryEntry(
                self.ADDRESS,
                sharers=frozenset((self.REQUESTER, self.PEER)),
                unique_owner=self.CLEAN_PEER,
                shared_dirty_owner=self.PEER,
            )

    def test_home_accepts_i_origin_against_current_holders(
        self,
    ) -> None:
        homes = (
            self.build_home(sharers=frozenset((self.PEER,))),
            self.build_home(
                sharers=frozenset(),
                unique_owner=self.PEER,
            ),
        )
        for home in homes:
            with self.subTest(
                unique_owner=home.initial_state().directory[
                    self.ADDRESS
                ].unique_owner
            ):
                accepted = self.apply(
                    home,
                    home.initial_state(),
                    ChiHomeAcceptCleanUnique(self.request_packet()),
                )
                self.assertEqual(1, len(accepted.emissions))
                self.assertEqual(
                    self.PEER,
                    accepted.emissions[0].target_id,
                )
                self.assertIsInstance(
                    accepted.emissions[0].message,
                    ChiSnpCleanInvalidMessage,
                )

    def test_comp_and_comp_ack_preserve_both_correlation_domains(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.SC,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCleanUnique(self.request()),
        )
        wrong_comp = ChiNetworkPacket.response(
            ChiCompMessage(
                transaction_id=self.TXN_ID + 1,
                data_buffer_id=self.DBID,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

        rejected_comp = requester.step(
            issued.state,
            ChiRnAcceptComp(wrong_comp),
        )

        self.assert_fault_rule(
            rejected_comp,
            "clean_unique_completion_identity",
        )
        self.assertEqual(issued.state, rejected_comp.state)

        home = self.build_home(sharers=frozenset((self.REQUESTER,)))
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCleanUnique(self.request_packet()),
        )
        bad_acks = (
            (
                ChiCompAckMessage(transaction_id=self.DBID + 1),
                "completion_ack_identity",
            ),
            (
                ChiCompAckMessage(
                    transaction_id=self.DBID,
                    response=1,
                ),
                "clean_unique_completion_ack_state",
            ),
            (
                ChiCompAckMessage(
                    transaction_id=self.DBID,
                    trace_tag=True,
                ),
                "clean_unique_completion_ack_state",
            ),
        )
        for message, expected_rule in bad_acks:
            with self.subTest(rule=expected_rule, message=message):
                packet = ChiNetworkPacket.response(
                    message,
                    source_id=self.REQUESTER,
                    target_id=self.HOME,
                )
                rejected_ack = home.step(
                    accepted.state,
                    ChiHomeAcceptCompAck(packet),
                )
                self.assert_fault_rule(rejected_ack, expected_rule)
                self.assertEqual(accepted.state, rejected_ack.state)


if __name__ == "__main__":
    unittest.main()
