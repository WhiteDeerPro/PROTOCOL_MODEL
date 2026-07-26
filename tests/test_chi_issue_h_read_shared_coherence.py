from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeDirectoryEntry,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiReadSharedMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiIssueHDatProfile,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitCoherentRead,
)


class ChiIssueHReadSharedCoherenceTest(unittest.TestCase):
    REQUESTER = 0x07
    OWNER = 0x08
    SHARER = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0x0123_4567_89AB_CDEF

    def build_session(self) -> ChiCoherenceSession:
        owner = build_chi_cache_participant_fixture(
            "rn_owner",
            self.OWNER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
            ),
        )
        requester = build_chi_cache_participant_fixture(
            "rn_requester",
            self.REQUESTER,
            self.HOME,
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.DATA,
                    unique_owner=self.OWNER,
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
        )
        return ChiCoherenceSession(
            "read_shared_clean_owner",
            home,
            {
                self.REQUESTER: requester,
                self.OWNER: owner,
            },
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_clean_unique_owner_downgrades_and_requester_joins_sharers(
        self,
    ) -> None:
        session = self.build_session()
        state = session.initial_state()
        request = ChiReadSharedMessage(
            transaction_id=0x12,
            address=self.ADDRESS,
            size=6,
            expect_completion_ack=True,
        )

        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        request_packet = issued.emissions[0]
        self.assertEqual(self.REQUESTER, request_packet.source_id)
        self.assertEqual(self.HOME, request_packet.target_id)

        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(request_packet),
        )
        snoop_packet = accepted.emissions[0]
        self.assertEqual(self.HOME, snoop_packet.source_id)
        self.assertEqual(self.OWNER, snoop_packet.target_id)
        self.assertEqual(0, snoop_packet.packet_index)
        self.assertEqual(1, snoop_packet.packet_count)
        self.assertEqual(0x100, snoop_packet.message.transaction_id)

        snooped = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        snoop_response = snooped.emissions[0]
        self.assertEqual(ChiRespCode.SC, snoop_response.message.response)
        self.assertEqual(
            ChiCacheState.SC,
            snooped.state.request_nodes[self.OWNER]
            .lines[self.ADDRESS]
            .state,
        )

        completed = self.apply(
            session,
            snooped.state,
            ChiDeliverCoherencePacket(snoop_response),
        )
        comp_data = completed.emissions[0]
        self.assertEqual(request.transaction_id, comp_data.message.transaction_id)
        self.assertEqual(0x200, comp_data.message.data_buffer_id)
        self.assertEqual(ChiRespCode.SC, comp_data.message.response)
        self.assertEqual(self.DATA, comp_data.message.data)
        self.assertFalse(
            comp_data.explain_profile(
                ChiIssueHDatProfile(data_width=512),
            )
        )

        installed = self.apply(
            session,
            completed.state,
            ChiDeliverCoherencePacket(comp_data),
        )
        comp_ack = installed.emissions[0]
        self.assertEqual(0x200, comp_ack.message.transaction_id)
        self.assertEqual(self.REQUESTER, comp_ack.source_id)
        self.assertEqual(self.HOME, comp_ack.target_id)

        retired = self.apply(
            session,
            installed.state,
            ChiDeliverCoherencePacket(comp_ack),
        )
        self.assertFalse(retired.emissions)
        self.assertTrue(session.is_quiescent(retired.state))
        directory = retired.state.home.directory[self.ADDRESS]
        self.assertIsNone(directory.unique_owner)
        self.assertEqual(
            frozenset((self.REQUESTER, self.OWNER)),
            directory.sharers,
        )
        self.assertEqual(
            ChiCacheState.SC,
            retired.state.request_nodes[self.REQUESTER]
            .lines[self.ADDRESS]
            .state,
        )
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

    def test_snoop_fanout_uses_target_copies_not_fragment_indices(
        self,
    ) -> None:
        requester = build_chi_cache_participant_fixture(
            "rn_requester",
            self.REQUESTER,
            self.HOME,
        )
        holders = {
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
            for node_id in (self.OWNER, self.SHARER)
        }
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.DATA,
                    sharers=frozenset(holders),
                ),
            ),
        )
        session = ChiCoherenceSession(
            "read_shared_fanout",
            home,
            {
                self.REQUESTER: requester,
                **holders,
            },
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadSharedMessage(
                    transaction_id=1,
                    address=self.ADDRESS,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        self.assertEqual(
            {self.OWNER, self.SHARER},
            {packet.target_id for packet in accepted.emissions},
        )
        self.assertEqual(
            1,
            len({id(packet.message) for packet in accepted.emissions}),
        )
        self.assertTrue(
            all(
                packet.packet_index == 0 and packet.packet_count == 1
                for packet in accepted.emissions
            )
        )


if __name__ == "__main__":
    unittest.main()
