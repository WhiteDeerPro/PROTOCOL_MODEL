from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCoherentTransactionPending,
    ChiHomeDirectoryEntry,
    ChiRnAcceptSnoop,
    ChiRnWriteCacheLine,
    ChiSnoopResult,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiNetworkPacket,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiSnpRespDataMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitCoherentRead,
    ChiWriteUniqueCacheLine,
)


class ChiIssueHDirtyUniqueCoherenceTest(unittest.TestCase):
    REQUESTER = 0x07
    OWNER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    BACKING_DATA = 0x1122
    DIRTY_DATA = (1 << 400) | 0xD17_7

    def build_session(self) -> ChiCoherenceSession:
        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
        )
        owner = build_chi_cache_participant_fixture(
            "owner",
            self.OWNER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.BACKING_DATA,
                ),
            ),
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.BACKING_DATA,
                    unique_owner=self.OWNER,
                ),
            ),
            allow_dirty_data_transfer=True,
        )
        return ChiCoherenceSession(
            "dirty_unique_transfer",
            home,
            {
                self.REQUESTER: requester,
                self.OWNER: owner,
            },
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                )
            ),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset((self.OWNER,)),
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_local_write_and_read_unique_transfer_dirty_responsibility(
        self,
    ) -> None:
        session = self.build_session()
        state = session.initial_state()

        dirtied = self.apply(
            session,
            state,
            ChiWriteUniqueCacheLine(
                self.OWNER,
                self.ADDRESS,
                self.DIRTY_DATA,
            ),
        )
        owner_line = dirtied.state.request_nodes[self.OWNER].lines[
            self.ADDRESS
        ]
        self.assertIs(ChiCacheState.UD, owner_line.state)
        self.assertEqual(self.DIRTY_DATA, owner_line.data)
        self.assertEqual(
            self.BACKING_DATA,
            dirtied.state.home.directory[self.ADDRESS].data,
        )

        request = ChiReadUniqueMessage(0x12, self.ADDRESS)
        issued = self.apply(
            session,
            dirtied.state,
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        home_accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        snoop_packet = home_accepted.emissions[0]
        self.assertIsInstance(snoop_packet.message, ChiSnpUniqueMessage)
        self.assertTrue(snoop_packet.message.return_to_source)

        snooped = self.apply(
            session,
            home_accepted.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        self.assertIs(
            ChiCacheState.I,
            snooped.state.request_nodes[self.OWNER]
            .lines[self.ADDRESS]
            .state,
        )
        snoop_data_packet = snooped.emissions[0]
        self.assertIsInstance(
            snoop_data_packet.message,
            ChiSnpRespDataMessage,
        )
        self.assertEqual(
            ChiRespCode.I_PD,
            snoop_data_packet.message.response,
        )
        self.assertTrue(snoop_data_packet.message.passes_dirty)
        self.assertEqual(self.DIRTY_DATA, snoop_data_packet.message.data)

        collected = self.apply(
            session,
            snooped.state,
            ChiDeliverCoherencePacket(snoop_data_packet),
        )
        completion_packet = collected.emissions[0]
        self.assertIsInstance(
            completion_packet.message,
            ChiCompDataMessage,
        )
        self.assertEqual(
            ChiRespCode.UD_PD,
            completion_packet.message.response,
        )
        self.assertTrue(completion_packet.message.passes_dirty)
        self.assertEqual(self.DIRTY_DATA, completion_packet.message.data)

        installed = self.apply(
            session,
            collected.state,
            ChiDeliverCoherencePacket(completion_packet),
        )
        requester_line = installed.state.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        self.assertIs(ChiCacheState.UD, requester_line.state)
        self.assertEqual(self.DIRTY_DATA, requester_line.data)

        retired = self.apply(
            session,
            installed.state,
            ChiDeliverCoherencePacket(installed.emissions[0]),
        )
        entry = retired.state.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertEqual(self.BACKING_DATA, entry.data)
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    def test_shared_line_requires_upgrade_before_local_write(self) -> None:
        node = build_chi_cache_participant_fixture(
            "shared",
            self.OWNER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    self.BACKING_DATA,
                ),
            ),
        )

        transition = node.step(
            node.initial_state(),
            ChiRnWriteCacheLine(
                self.ADDRESS,
                self.DIRTY_DATA,
            ),
        )

        self.assertIsNotNone(transition.fault)
        self.assertIn("permission upgrade", transition.fault.reason)

    def test_shared_line_can_upgrade_then_become_dirty_unique(self) -> None:
        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    self.BACKING_DATA,
                ),
            ),
        )
        peer = build_chi_cache_participant_fixture(
            "peer",
            self.OWNER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    self.BACKING_DATA,
                ),
            ),
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.BACKING_DATA,
                    sharers=frozenset((self.REQUESTER, self.OWNER)),
                ),
            ),
            allow_dirty_data_transfer=True,
        )
        session = ChiCoherenceSession(
            "shared_upgrade",
            home,
            {
                self.REQUESTER: requester,
                self.OWNER: peer,
            },
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                )
            ),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset((self.OWNER,)),
        )
        state = session.initial_state()

        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(0x15, self.ADDRESS),
            ),
        )
        home_accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        snooped = self.apply(
            session,
            home_accepted.state,
            ChiDeliverCoherencePacket(home_accepted.emissions[0]),
        )
        collected = self.apply(
            session,
            snooped.state,
            ChiDeliverCoherencePacket(snooped.emissions[0]),
        )
        installed = self.apply(
            session,
            collected.state,
            ChiDeliverCoherencePacket(collected.emissions[0]),
        )
        upgraded = self.apply(
            session,
            installed.state,
            ChiDeliverCoherencePacket(installed.emissions[0]),
        )

        requester_line = upgraded.state.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        peer_line = upgraded.state.request_nodes[
            self.OWNER
        ].lines[self.ADDRESS]
        directory = upgraded.state.home.directory[self.ADDRESS]
        self.assertIs(ChiCacheState.UC, requester_line.state)
        self.assertIs(ChiCacheState.I, peer_line.state)
        self.assertEqual(self.REQUESTER, directory.unique_owner)
        self.assertFalse(directory.sharers)

        written = self.apply(
            session,
            upgraded.state,
            ChiWriteUniqueCacheLine(
                self.REQUESTER,
                self.ADDRESS,
                self.DIRTY_DATA,
            ),
        )
        self.assertIs(
            ChiCacheState.UD,
            written.state.request_nodes[self.REQUESTER]
            .lines[self.ADDRESS]
            .state,
        )

    def test_one_transaction_cannot_collect_two_dirty_owners(self) -> None:
        with self.assertRaisesRegex(ValueError, "two dirty owners"):
            ChiCoherentTransactionPending(
                requester_id=self.REQUESTER,
                request=ChiReadUniqueMessage(0x12, self.ADDRESS),
                snoop_transaction_id=0x100,
                data_buffer_id=0x200,
                snoop_targets=frozenset((self.OWNER, self.OWNER + 1)),
                snoop_results={
                    self.OWNER: ChiSnoopResult(
                        ChiRespCode.I_PD,
                        self.DIRTY_DATA,
                    ),
                    self.OWNER + 1: ChiSnoopResult(
                        ChiRespCode.I_PD,
                        self.DIRTY_DATA + 1,
                    ),
                },
            )

    def test_plain_snp_shared_does_not_imply_a_dirty_downgrade_policy(
        self,
    ) -> None:
        node = build_chi_cache_participant_fixture(
            "dirty_owner",
            self.OWNER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UD,
                    self.DIRTY_DATA,
                ),
            ),
        )
        snoop = ChiNetworkPacket.snoop(
            ChiSnpSharedMessage(0x101, self.ADDRESS),
            source_id=self.HOME,
            target_id=self.OWNER,
        )

        transition = node.step(
            node.initial_state(),
            ChiRnAcceptSnoop(snoop),
        )

        self.assertIsNotNone(transition.fault)
        self.assertIn("dirty-shared policy", transition.fault.reason)

    def test_clean_only_profile_rejects_an_initial_ud_line(self) -> None:
        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
        )
        dirty_owner = build_chi_cache_participant_fixture(
            "dirty_owner",
            self.OWNER,
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
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.BACKING_DATA,
                    unique_owner=self.OWNER,
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "cannot consume a dirty owner"):
            ChiCoherenceSession(
                "clean_only",
                home,
                {
                    self.REQUESTER: requester,
                    self.OWNER: dirty_owner,
                },
                enabled_features=frozenset(
                    (CHI_FEATURE_CLEAN_READ_UNIQUE,)
                ),
                requester_node_ids=frozenset((self.REQUESTER,)),
                snoopee_node_ids=frozenset((self.OWNER,)),
            )

    def test_read_shared_waits_for_a_dirty_shared_policy(self) -> None:
        dirty_session = self.build_session()

        with self.assertRaisesRegex(ValueError, "dirty-shared policy"):
            ChiCoherenceSession(
                "unsupported_dirty_shared_mix",
                dirty_session.home,
                dirty_session.request_nodes,
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_SHARED,
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                    )
                ),
                requester_node_ids=dirty_session.requester_node_ids,
                snoopee_node_ids=dirty_session.snoopee_node_ids,
            )

        with self.assertRaisesRegex(ValueError, "dirty-shared policy"):
            ChiCoherenceSession(
                "unsupported_mesi_read_shared_mix",
                dirty_session.home,
                dirty_session.request_nodes,
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_SHARED,
                        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
                    )
                ),
                requester_node_ids=dirty_session.requester_node_ids,
                snoopee_node_ids=dirty_session.snoopee_node_ids,
            )


if __name__ == "__main__":
    unittest.main()
