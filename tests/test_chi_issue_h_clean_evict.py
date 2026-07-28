from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptEvict,
    ChiHomeDirectoryEntry,
    ChiRnAcceptComp,
    ChiRnAcceptSnoop,
    ChiRnIssueEvict,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiEvictMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
    ChiRespErr,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompMessage,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_FEATURE_CLEAN_EVICT,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiSubmitEvict,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHCleanEvictTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    OTHER_ADDRESS = 0x8040
    DATA = (1 << 400) | 0xE71C7
    OTHER_DATA = (1 << 401) | 0xE71C8
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
        state: ChiCacheState,
        *,
        initial_lines: tuple[ChiCacheLine, ...] | None = None,
    ):
        if initial_lines is None:
            initial_lines = (
                ChiCacheLine(
                    self.ADDRESS,
                    state,
                    (
                        None
                        if state in (ChiCacheState.I, ChiCacheState.UCE)
                        else self.DATA
                    ),
                ),
            )
        return build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=initial_lines,
        )

    def build_home(
        self,
        *,
        sharers: frozenset[int] = frozenset(),
        unique_owner: int | None = None,
        shared_dirty_owner: int | None = None,
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
        )

    def request(
        self,
        *,
        transaction_id: int | None = None,
        address: int | None = None,
    ) -> ChiEvictMessage:
        return ChiEvictMessage(
            self.TXN_ID if transaction_id is None else transaction_id,
            self.ADDRESS if address is None else address,
        )

    def request_packet(
        self,
        *,
        source_id: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            self.request(),
            source_id=(
                self.REQUESTER if source_id is None else source_id
            ),
            target_id=self.HOME,
        )

    def completion_packet(
        self,
        *,
        transaction_id: int | None = None,
        data_buffer_id: int = 0,
        response: ChiRespCode = ChiRespCode.I,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiCompMessage(
                transaction_id=(
                    self.TXN_ID
                    if transaction_id is None
                    else transaction_id
                ),
                data_buffer_id=data_buffer_id,
                response=response,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def build_session(self) -> ChiCoherenceSession:
        requester = self.build_rn(ChiCacheState.UC)
        home = self.build_home(unique_owner=self.REQUESTER)
        return ChiCoherenceSession(
            "clean_evict",
            home,
            {self.REQUESTER: requester},
            enabled_features=frozenset((CHI_FEATURE_CLEAN_EVICT,)),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset(),
        )

    def test_issue_silently_discards_sc_uc_and_uce_before_req(self) -> None:
        for initial_state in (
            ChiCacheState.SC,
            ChiCacheState.UC,
            ChiCacheState.UCE,
        ):
            with self.subTest(initial_state=initial_state):
                requester = self.build_rn(initial_state)
                initial = requester.initial_state()

                issued = self.apply(
                    requester,
                    initial,
                    ChiRnIssueEvict(self.request()),
                )

                line = issued.state.line_at(self.ADDRESS)
                assert line is not None
                self.assertIs(ChiCacheState.I, line.state)
                self.assertIsNone(line.data)
                self.assertNotIn(self.ADDRESS, issued.state.cache.lines)
                self.assertEqual(
                    self.request(),
                    issued.state.pending_transactions[self.TXN_ID],
                )
                self.assertEqual(1, len(issued.emissions))
                packet = issued.emissions[0]
                self.assertEqual(self.REQUESTER, packet.source_id)
                self.assertEqual(self.HOME, packet.target_id)
                self.assertEqual(self.request(), packet.message)

    def test_issue_rejects_i_ud_and_sd_without_mutation(self) -> None:
        for initial_state in (
            ChiCacheState.I,
            ChiCacheState.UD,
            ChiCacheState.SD,
        ):
            with self.subTest(initial_state=initial_state):
                requester = self.build_rn(initial_state)
                initial = requester.initial_state()

                rejected = requester.step(
                    initial,
                    ChiRnIssueEvict(self.request()),
                )

                self.assert_fault_rule(rejected, "evict_permission")
                self.assertEqual(initial, rejected.state)
                self.assertFalse(rejected.emissions)

    def test_issue_rejects_reserved_pas_before_discarding_payload(
        self,
    ) -> None:
        requester = self.build_rn(ChiCacheState.UC)
        initial = requester.initial_state()

        rejected = requester.step(
            initial,
            ChiRnIssueEvict(
                ChiEvictMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                    pas=6,
                )
            ),
        )

        self.assert_fault_rule(rejected, "evict_attributes")
        self.assertEqual(initial, rejected.state)
        self.assertFalse(rejected.emissions)

    def test_duplicate_transaction_id_is_rejected_before_line_reservation(
        self,
    ) -> None:
        requester = self.build_rn(
            ChiCacheState.UC,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
                ChiCacheLine(
                    self.OTHER_ADDRESS,
                    ChiCacheState.UC,
                    self.OTHER_DATA,
                ),
            ),
        )
        first = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueEvict(self.request()),
        )

        duplicate = requester.step(
            first.state,
            ChiRnIssueEvict(
                self.request(address=self.OTHER_ADDRESS)
            ),
        )

        self.assert_fault_rule(duplicate, "duplicate_transaction")
        self.assertEqual(first.state, duplicate.state)
        other_line = duplicate.state.line_at(self.OTHER_ADDRESS)
        assert other_line is not None
        self.assertIs(ChiCacheState.UC, other_line.state)
        self.assertEqual(self.OTHER_DATA, other_line.data)

    def test_home_removes_a_matching_unique_holder_without_other_mutation(
        self,
    ) -> None:
        home = self.build_home(unique_owner=self.REQUESTER)
        initial = home.initial_state()
        backing_before = initial.backing.line_at(self.ADDRESS)

        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        entry = accepted.state.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        self.assertEqual(
            backing_before,
            accepted.state.backing.line_at(self.ADDRESS),
        )
        self.assertEqual(
            initial.next_snoop_transaction_id,
            accepted.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            initial.next_data_buffer_id,
            accepted.state.next_data_buffer_id,
        )
        self.assertFalse(accepted.state.pending)
        self.assertFalse(accepted.state.pending_writebacks)
        self.assert_evict_completion(accepted.emissions)

    def test_home_removes_only_the_matching_shared_holder(self) -> None:
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER)),
        )
        initial = home.initial_state()

        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        entry = accepted.state.directory[self.ADDRESS]
        self.assertEqual(frozenset((self.PEER,)), entry.sharers)
        self.assertIsNone(entry.unique_owner)
        self.assertEqual(initial.backing, accepted.state.backing)
        self.assertEqual(
            initial.next_snoop_transaction_id,
            accepted.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            initial.next_data_buffer_id,
            accepted.state.next_data_buffer_id,
        )
        self.assert_evict_completion(accepted.emissions)

    def test_stale_non_holder_evict_is_a_no_op_hint_with_comp_i(
        self,
    ) -> None:
        home = self.build_home(sharers=frozenset((self.PEER,)))
        initial = home.initial_state()

        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assertEqual(initial.directory, accepted.state.directory)
        self.assertEqual(initial.backing, accepted.state.backing)
        self.assertEqual(
            initial.next_snoop_transaction_id,
            accepted.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            initial.next_data_buffer_id,
            accepted.state.next_data_buffer_id,
        )
        self.assert_evict_completion(accepted.emissions)

    def test_absent_directory_entry_is_a_no_op_hint_with_comp_i(
        self,
    ) -> None:
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.DATA),
                ),
            ),
            initial_directory=(),
        )
        initial = home.initial_state()

        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assertFalse(accepted.state.directory)
        self.assertEqual(initial.backing, accepted.state.backing)
        self.assert_evict_completion(accepted.emissions)

    def test_home_rejects_address_outside_its_backing(self) -> None:
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
            ),
            initial_directory=(),
        )
        initial = home.initial_state()

        rejected = home.step(
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assert_fault_rule(rejected, "address_home")
        self.assertEqual(initial, rejected.state)
        self.assertFalse(rejected.emissions)

    def test_home_does_not_drop_shared_dirty_responsibility(self) -> None:
        home = self.build_home(
            sharers=frozenset((self.REQUESTER, self.PEER)),
            shared_dirty_owner=self.REQUESTER,
        )
        initial = home.initial_state()

        accepted = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assertEqual(initial.directory, accepted.state.directory)
        self.assertEqual(initial.backing, accepted.state.backing)
        self.assert_evict_completion(accepted.emissions)

    def test_home_rejects_reserved_pas_without_directory_mutation(
        self,
    ) -> None:
        home = self.build_home(unique_owner=self.REQUESTER)
        initial = home.initial_state()
        packet = ChiNetworkPacket.request(
            ChiEvictMessage(
                self.TXN_ID,
                self.ADDRESS,
                pas=7,
            ),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )

        rejected = home.step(
            initial,
            ChiHomeAcceptEvict(packet),
        )

        self.assert_fault_rule(rejected, "evict_profile")
        self.assertEqual(initial, rejected.state)
        self.assertFalse(rejected.emissions)

    def assert_evict_completion(self, emissions) -> ChiNetworkPacket:
        self.assertEqual(1, len(emissions))
        packet = emissions[0]
        self.assertEqual(self.HOME, packet.source_id)
        self.assertEqual(self.REQUESTER, packet.target_id)
        self.assertIsInstance(packet.message, ChiCompMessage)
        self.assertEqual(self.TXN_ID, packet.message.transaction_id)
        self.assertEqual(0, packet.message.data_buffer_id)
        self.assertIs(ChiRespCode.I, packet.message.response)
        return packet

    def test_comp_i_retires_rn_without_dbid_lease_or_comp_ack(self) -> None:
        requester = self.build_rn(ChiCacheState.UC)
        home = self.build_home(unique_owner=self.REQUESTER)
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueEvict(self.request()),
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptEvict(issued.emissions[0]),
        )
        completion = self.assert_evict_completion(accepted.emissions)
        completion = ChiNetworkPacket.response(
            ChiCompMessage(
                transaction_id=self.TXN_ID,
                data_buffer_id=0xABC,
                response=ChiRespCode.I,
            ),
            source_id=completion.source_id,
            target_id=completion.target_id,
        )

        retired = self.apply(
            requester,
            issued.state,
            ChiRnAcceptComp(completion),
        )

        self.assertFalse(retired.state.pending_transactions)
        self.assertFalse(retired.emissions)
        line = retired.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertTrue(requester.is_quiescent(retired.state))
        self.assertTrue(home.is_quiescent(accepted.state))

    def test_pending_evict_answers_same_line_snoop_i_and_keeps_correlation(
        self,
    ) -> None:
        requester = self.build_rn(ChiCacheState.UC)
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueEvict(self.request()),
        )
        snoop_packet = ChiNetworkPacket.snoop(
            ChiSnpUniqueMessage(
                self.SNOOP_ID,
                self.ADDRESS,
                return_to_source=True,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

        snooped = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(snoop_packet),
        )

        self.assertEqual(
            issued.state.pending_transactions,
            snooped.state.pending_transactions,
        )
        line = snooped.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertEqual(1, len(snooped.emissions))
        response = snooped.emissions[0]
        self.assertIsInstance(response.message, ChiSnpRespMessage)
        self.assertIs(ChiRespCode.I, response.message.response)
        self.assertEqual(self.SNOOP_ID, response.message.transaction_id)
        self.assertEqual(self.REQUESTER, response.source_id)
        self.assertEqual(self.HOME, response.target_id)

    def test_rn_rejects_wrong_completion_and_preserves_pending(self) -> None:
        requester = self.build_rn(ChiCacheState.UC)
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueEvict(self.request()),
        )
        wrong_cases = (
            (
                self.completion_packet(
                    transaction_id=self.TXN_ID + 1,
                ),
                "clean_unique_completion_identity",
            ),
            (
                self.completion_packet(response=ChiRespCode.UC),
                "evict_completion_state",
            ),
            (
                ChiNetworkPacket.response(
                    ChiCompMessage(
                        self.TXN_ID,
                        0,
                        response_error=ChiRespErr.NDERR,
                        response=ChiRespCode.I,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                ),
                "evict_completion_state",
            ),
            (
                ChiNetworkPacket.response(
                    ChiCompMessage(
                        self.TXN_ID,
                        0,
                        response=ChiRespCode.I,
                        tag_operation=1,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                ),
                "evict_completion_state",
            ),
        )
        for packet, rule in wrong_cases:
            with self.subTest(rule=rule):
                rejected = requester.step(
                    issued.state,
                    ChiRnAcceptComp(packet),
                )
                self.assert_fault_rule(rejected, rule)
                self.assertEqual(issued.state, rejected.state)
                self.assertFalse(rejected.emissions)

    def test_session_requires_home_completion_evidence_and_rejects_late_comp(
        self,
    ) -> None:
        session = self.build_session()
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitEvict(self.REQUESTER, self.request()),
        )
        request_packet = issued.emissions[0]
        self.assertFalse(issued.state.expected_evict_completions)

        early = session.step(
            issued.state,
            ChiDeliverCoherencePacket(self.completion_packet()),
        )
        self.assert_fault_rule(early, "evict_completion_correlation")
        self.assertEqual(issued.state, early.state)

        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(request_packet),
        )
        completion = self.assert_evict_completion(accepted.emissions)
        key = (self.REQUESTER, self.TXN_ID)
        self.assertEqual(
            completion.message,
            accepted.state.expected_evict_completions[key],
        )
        self.assertIsNone(
            accepted.state.home.directory[self.ADDRESS].unique_owner
        )

        wrong = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(
                self.completion_packet(data_buffer_id=1)
            ),
        )
        self.assert_fault_rule(wrong, "evict_completion_correlation")
        self.assertEqual(accepted.state, wrong.state)

        duplicate_request = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(request_packet),
        )
        self.assert_fault_rule(
            duplicate_request,
            "duplicate_evict_request",
        )
        self.assertEqual(accepted.state, duplicate_request.state)

        retired = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assertFalse(retired.emissions)
        self.assertFalse(retired.state.expected_evict_completions)
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertFalse(
            ChiCoherenceInvariantMonitor().explain(
                retired.state.home,
                retired.state.request_nodes,
            )
        )

        late = session.step(
            retired.state,
            ChiDeliverCoherencePacket(completion),
        )
        self.assert_fault_rule(
            late,
            "dataless_completion_correlation",
        )
        self.assertEqual(retired.state, late.state)

if __name__ == "__main__":
    unittest.main()
