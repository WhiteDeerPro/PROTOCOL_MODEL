from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptCopyBackData,
    ChiHomeAcceptWriteBackFull,
    ChiHomeDirectoryEntry,
    ChiHomeWriteBackAdmission,
    ChiRnAcceptCompDBIDResp,
    ChiRnIssueWriteBackFull,
    ChiRnWriteBackOutcome,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCleanUniqueMessage,
    ChiCompDBIDRespMessage,
    ChiCopyBackWrDataMessage,
    ChiNetworkPacket,
    ChiRespCode,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitCleanUnique,
    ChiSubmitWriteBackFull,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHWriteBackLifecycleTest(unittest.TestCase):
    RN = 0x07
    NEW_RN = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    STALE_BACKING = 0x1122
    DIRTY_DATA = (1 << 400) | 0xD177

    def build_participants(self):
        rn = build_chi_cache_participant_fixture(
            "dirty_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UD,
                    self.DIRTY_DATA,
                ),
            ),
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.STALE_BACKING),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.RN,
                ),
            ),
            allow_dirty_data_transfer=True,
        )
        return rn, home

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_ud_writeback_commits_only_after_copyback_data(self) -> None:
        rn, home = self.build_participants()
        rn_state = rn.initial_state()
        home_state = home.initial_state()
        request = ChiWriteBackFullMessage(0x12, self.ADDRESS)

        issued = self.apply(
            rn,
            rn_state,
            ChiRnIssueWriteBackFull(request),
        )
        self.assertEqual(
            request,
            issued.state.pending_writebacks[0x12].request,
        )
        self.assertIs(
            ChiCacheState.UD,
            issued.state.lines[self.ADDRESS].state,
        )
        self.assertEqual(self.DIRTY_DATA, issued.state.lines[self.ADDRESS].data)

        accepted = self.apply(
            home,
            home_state,
            ChiHomeAcceptWriteBackFull(issued.emissions[0]),
        )
        dbid_response_packet = accepted.emissions[0]
        self.assertIsInstance(
            dbid_response_packet.message,
            ChiCompDBIDRespMessage,
        )
        dbid = dbid_response_packet.message.data_buffer_id
        self.assertIn(dbid, accepted.state.pending_writebacks)
        entry_before_data = accepted.state.directory[self.ADDRESS]
        self.assertEqual(
            self.STALE_BACKING,
            accepted.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(self.RN, entry_before_data.unique_owner)

        copied = self.apply(
            rn,
            issued.state,
            ChiRnAcceptCompDBIDResp(dbid_response_packet),
        )
        self.assertFalse(copied.state.pending_writebacks)
        self.assertIs(
            ChiCacheState.I,
            copied.state.lines[self.ADDRESS].state,
        )
        self.assertNotIn(self.ADDRESS, copied.state.cache.lines)
        copyback_packet = copied.emissions[0]
        self.assertIsInstance(
            copyback_packet.message,
            ChiCopyBackWrDataMessage,
        )
        self.assertEqual(dbid, copyback_packet.message.transaction_id)
        self.assertEqual(self.DIRTY_DATA, copyback_packet.message.data)
        self.assertIs(ChiRespCode.UD_PD, copyback_packet.message.response)

        committed = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptCopyBackData(copyback_packet),
        )
        entry = committed.state.directory[self.ADDRESS]
        self.assertEqual(
            self.DIRTY_DATA,
            committed.state.backing.line_at(self.ADDRESS).data,
        )
        self.assertIsNone(entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertFalse(committed.state.pending_writebacks)
        self.assertTrue(rn.is_quiescent(copied.state))
        self.assertTrue(home.is_quiescent(committed.state))

    def test_writeback_requires_dirty_unique_residency(self) -> None:
        rn = build_chi_cache_participant_fixture(
            "clean_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.STALE_BACKING,
                ),
            ),
        )

        transition = rn.step(
            rn.initial_state(),
            ChiRnIssueWriteBackFull(
                ChiWriteBackFullMessage(0x13, self.ADDRESS)
            ),
        )

        self.assertIsNotNone(transition.fault)
        self.assertIn("resident UD", transition.fault.reason)

    def test_home_profile_must_enable_dirty_transfer(self) -> None:
        rn, _ = self.build_participants()
        home = ChiCoherentHomeNode(
            "clean_only_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "clean_only_home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.STALE_BACKING),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.RN,
                ),
            ),
        )
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteBackFull(
                ChiWriteBackFullMessage(0x15, self.ADDRESS)
            ),
        )

        transition = home.step(
            home.initial_state(),
            ChiHomeAcceptWriteBackFull(issued.emissions[0]),
        )

        self.assertIsNotNone(transition.fault)
        self.assertIn(
            "does not enable dirty-data transfer",
            transition.fault.reason,
        )

    def test_packet_delivery_session_dispatches_the_writeback(self) -> None:
        rn, home = self.build_participants()
        session = ChiCoherenceSession(
            "writeback_session",
            home,
            {self.RN: rn},
            enabled_features=frozenset(
                (CHI_FEATURE_DIRTY_WRITEBACK,)
            ),
            requester_node_ids=frozenset((self.RN,)),
            snoopee_node_ids=frozenset(),
        )
        state = session.initial_state()

        issued = self.apply(
            session,
            state,
            ChiSubmitWriteBackFull(
                self.RN,
                ChiWriteBackFullMessage(0x14, self.ADDRESS),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(accepted.emissions[0]),
        )
        committed = self.apply(
            session,
            copied.state,
            ChiDeliverCoherencePacket(copied.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(committed.state))
        self.assertEqual(
            self.DIRTY_DATA,
            committed.state.home.backing.line_at(self.ADDRESS).data,
        )
        self.assertIsNone(
            committed.state.home.directory[self.ADDRESS].unique_owner
        )

    def test_home_rejects_copyback_after_backing_version_changes(self) -> None:
        rn, home = self.build_participants()
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteBackFull(
                ChiWriteBackFullMessage(0x16, self.ADDRESS)
            ),
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptWriteBackFull(issued.emissions[0]),
        )
        copied = self.apply(
            rn,
            issued.state,
            ChiRnAcceptCompDBIDResp(accepted.emissions[0]),
        )
        prepared = home.backing_core.prepare_write(
            accepted.state.backing,
            self.ADDRESS,
            self.STALE_BACKING + 1,
        )
        changed_backing = home.backing_core.commit_write(
            accepted.state.backing,
            prepared,
        ).state
        changed_state = replace(
            accepted.state,
            backing=changed_backing,
        )

        rejected = home.step(
            changed_state,
            ChiHomeAcceptCopyBackData(copied.emissions[0]),
        )

        self.assertIsNotNone(rejected.fault)
        assert rejected.fault is not None
        self.assertTrue(
            rejected.fault.rule.endswith("copyback_reservation_changed")
        )
        self.assertEqual(changed_state, rejected.state)

    def test_clean_unique_snoop_cancels_delayed_writeback_without_stale_commit(
        self,
    ) -> None:
        old_owner, home = self.build_participants()
        new_owner = build_chi_cache_participant_fixture(
            "new_owner",
            self.NEW_RN,
            self.HOME,
        )
        session = ChiCoherenceSession(
            "clean_unique_writeback_cancel",
            home,
            {
                self.RN: old_owner,
                self.NEW_RN: new_owner,
            },
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                    CHI_FEATURE_DIRTY_WRITEBACK,
                )
            ),
            requester_node_ids=frozenset((self.RN, self.NEW_RN)),
            snoopee_node_ids=frozenset((self.RN, self.NEW_RN)),
        )
        state = session.initial_state()

        writeback_issued = self.apply(
            session,
            state,
            ChiSubmitWriteBackFull(
                self.RN,
                ChiWriteBackFullMessage(0x31, self.ADDRESS),
            ),
        )
        delayed_writeback = writeback_issued.emissions[0]
        clean_unique_issued = self.apply(
            session,
            writeback_issued.state,
            ChiSubmitCleanUnique(
                self.NEW_RN,
                ChiCleanUniqueMessage(0x32, self.ADDRESS),
            ),
        )
        clean_unique_at_home = self.apply(
            session,
            clean_unique_issued.state,
            ChiDeliverCoherencePacket(
                clean_unique_issued.emissions[0]
            ),
        )
        old_owner_snooped = self.apply(
            session,
            clean_unique_at_home.state,
            ChiDeliverCoherencePacket(
                clean_unique_at_home.emissions[0]
            ),
        )

        old_state = old_owner_snooped.state.request_nodes[self.RN]
        old_line = old_state.line_at(self.ADDRESS)
        assert old_line is not None
        self.assertIs(ChiCacheState.I, old_line.state)
        self.assertIs(
            ChiRnWriteBackOutcome.CANCELED_I,
            old_state.pending_writebacks[0x31].outcome,
        )
        snoop_data = old_owner_snooped.emissions[0].message
        self.assertEqual(self.DIRTY_DATA, snoop_data.data)
        self.assertIs(ChiRespCode.I_PD, snoop_data.response)

        clean_unique_collected = self.apply(
            session,
            old_owner_snooped.state,
            ChiDeliverCoherencePacket(
                old_owner_snooped.emissions[0]
            ),
        )
        new_owner_completed = self.apply(
            session,
            clean_unique_collected.state,
            ChiDeliverCoherencePacket(
                clean_unique_collected.emissions[0]
            ),
        )
        clean_unique_retired = self.apply(
            session,
            new_owner_completed.state,
            ChiDeliverCoherencePacket(
                new_owner_completed.emissions[0]
            ),
        )

        new_line = clean_unique_retired.state.request_nodes[
            self.NEW_RN
        ].line_at(self.ADDRESS)
        assert new_line is not None
        self.assertIs(ChiCacheState.UCE, new_line.state)
        before_cancel_entry = clean_unique_retired.state.home.directory[
            self.ADDRESS
        ]
        before_cancel_backing = (
            clean_unique_retired.state.home.backing.line_at(
                self.ADDRESS
            )
        )
        self.assertEqual(self.NEW_RN, before_cancel_entry.unique_owner)
        self.assertEqual(self.DIRTY_DATA, before_cancel_backing.data)

        canceled_at_home = self.apply(
            session,
            clean_unique_retired.state,
            ChiDeliverCoherencePacket(delayed_writeback),
        )
        home_pending = next(
            iter(canceled_at_home.state.home.pending_writebacks.values())
        )
        self.assertIs(
            ChiHomeWriteBackAdmission.SNOOP_CANCELED,
            home_pending.admission,
        )
        cancel_sent = self.apply(
            session,
            canceled_at_home.state,
            ChiDeliverCoherencePacket(canceled_at_home.emissions[0]),
        )
        copyback = cancel_sent.emissions[0].message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertIs(ChiRespCode.I, copyback.response)
        self.assertEqual(0, copyback.data)
        self.assertEqual(0, copyback.byte_enable)

        rejected_stale_data = session.step(
            cancel_sent.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.data(
                    ChiCopyBackWrDataMessage(
                        transaction_id=copyback.transaction_id,
                        data=self.DIRTY_DATA,
                        response=ChiRespCode.UD_PD,
                    ),
                    source_id=self.RN,
                    target_id=self.HOME,
                )
            ),
        )
        self.assertIsNotNone(rejected_stale_data.fault)
        assert rejected_stale_data.fault is not None
        self.assertTrue(
            rejected_stale_data.fault.rule.endswith(
                "copyback_cancellation_profile"
            )
        )
        self.assertEqual(cancel_sent.state, rejected_stale_data.state)

        retired = self.apply(
            session,
            cancel_sent.state,
            ChiDeliverCoherencePacket(cancel_sent.emissions[0]),
        )
        self.assertEqual(
            before_cancel_entry,
            retired.state.home.directory[self.ADDRESS],
        )
        self.assertEqual(
            before_cancel_backing,
            retired.state.home.backing.line_at(self.ADDRESS),
        )
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

        replayed_request = session.step(
            retired.state,
            ChiDeliverCoherencePacket(delayed_writeback),
        )
        self.assertIsNotNone(replayed_request.fault)
        assert replayed_request.fault is not None
        self.assertTrue(
            replayed_request.fault.rule.endswith(
                "writeback_cancellation_evidence"
            )
        )
        self.assertEqual(retired.state, replayed_request.state)


if __name__ == "__main__":
    unittest.main()
