from __future__ import annotations

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
    ChiRnAcceptCompDBIDResp,
    ChiRnIssueWriteBackFull,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDBIDRespMessage,
    ChiCopyBackWrDataMessage,
    ChiRespCode,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_DIRTY_WRITEBACK,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitWriteBackFull,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHWriteBackLifecycleTest(unittest.TestCase):
    RN = 0x07
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
        self.assertEqual(request, issued.state.pending_writebacks[0x12])
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


if __name__ == "__main__":
    unittest.main()
