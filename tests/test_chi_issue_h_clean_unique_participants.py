from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptCleanUnique,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptSnoopResponse,
    ChiHomeDirectoryEntry,
    ChiRnAcceptComp,
    ChiRnAcceptSnoop,
    ChiRnIssueCleanUnique,
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
)


class ChiIssueHCleanUniqueParticipantTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
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

    def build_rn(self, name: str, node_id: int, state: ChiCacheState):
        return build_chi_cache_participant_fixture(
            name,
            node_id,
            self.HOME,
            initial_lines=(
                ChiCacheLine(self.ADDRESS, state, self.DATA),
            ),
        )

    def build_home(
        self,
        *,
        sharers: frozenset[int],
        unique_owner: int | None = None,
        allow_dirty_data_transfer: bool = False,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.DATA,
                    sharers=sharers,
                    unique_owner=unique_owner,
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
        self.assertEqual(self.DATA, entry.data)
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertTrue(requester.is_quiescent(installed.state))
        self.assertTrue(home.is_quiescent(retired.state))

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

    def test_snp_clean_invalid_rejects_a_dirty_peer_without_mutation(
        self,
    ) -> None:
        peer = self.build_rn("dirty_peer", self.PEER, ChiCacheState.UD)
        state = peer.initial_state()
        snoop = ChiNetworkPacket.snoop(
            ChiSnpCleanInvalidMessage(self.SNOOP_ID, self.ADDRESS),
            source_id=self.HOME,
            target_id=self.PEER,
        )

        transition = peer.step(state, ChiRnAcceptSnoop(snoop))

        self.assert_fault_rule(transition, "clean_unique_dirty_peer")
        self.assertEqual(state, transition.state)
        self.assertFalse(transition.emissions)

    def test_home_rejects_clean_unique_dirty_data_without_mutation(
        self,
    ) -> None:
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER)),
            allow_dirty_data_transfer=True,
        )
        accepted = self.apply(
            home,
            home.initial_state(),
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

        transition = home.step(
            accepted.state,
            ChiHomeAcceptSnoopResponse(dirty_response),
        )

        self.assert_fault_rule(transition, "clean_unique_dirty_data")
        self.assertEqual(accepted.state, transition.state)
        self.assertFalse(transition.emissions)

    def test_home_requires_matching_shared_directory_authority(
        self,
    ) -> None:
        cases = (
            (
                self.build_home(sharers=frozenset((self.PEER,))),
                "clean_unique_requester_state",
            ),
            (
                self.build_home(
                    sharers=frozenset(),
                    unique_owner=self.PEER,
                ),
                "clean_unique_directory_state",
            ),
        )
        for home, expected_rule in cases:
            with self.subTest(rule=expected_rule):
                state = home.initial_state()
                transition = home.step(
                    state,
                    ChiHomeAcceptCleanUnique(self.request_packet()),
                )
                self.assert_fault_rule(transition, expected_rule)
                self.assertEqual(state, transition.state)
                self.assertFalse(transition.emissions)

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
