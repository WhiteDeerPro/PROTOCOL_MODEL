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
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiIssueHDatProfile,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiReadUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitCoherentRead,
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

    def build_session(self) -> ChiCoherenceSession:
        requester = build_chi_cache_participant_fixture(
            "rn_requester",
            self.REQUESTER,
            self.HOME,
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
                    sharers=frozenset(sharers),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
        )
        return ChiCoherenceSession(
            "read_unique_clean_sharers",
            home,
            {
                self.REQUESTER: requester,
                **sharers,
            },
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

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
