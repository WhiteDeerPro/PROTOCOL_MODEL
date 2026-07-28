from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCoherentTransactionPending,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptMakeUnique,
    ChiHomeAcceptSnoopResponse,
    ChiHomeDirectoryEntry,
    ChiRnAcceptComp,
    ChiRnAcceptSnoop,
    ChiRnIssueMakeUnique,
    ChiSnoopResult,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiMakeUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
    ChiRespErr,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompAckMessage,
    ChiCompMessage,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpMakeInvalidMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHMakeUniqueParticipantTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    OLD_DATA = (1 << 400) | 0x0D
    NEW_DATA = (1 << 500) | 0x4E57
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
                        else self.OLD_DATA
                    ),
                ),
            ),
        )

    def build_home(
        self,
        *,
        allow_dirty_data_transfer: bool = False,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.OLD_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.PEER,
                ),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
            allow_dirty_data_transfer=allow_dirty_data_transfer,
        )

    def request(self, **changes) -> ChiMakeUniqueMessage:
        values = {
            "transaction_id": self.TXN_ID,
            "address": self.ADDRESS,
        }
        values.update(changes)
        return ChiMakeUniqueMessage(**values)

    def test_make_unique_discards_dirty_peer_and_installs_local_store(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        peer = self.build_rn("peer", self.PEER, ChiCacheState.UD)
        home = self.build_home()
        requester_state = requester.initial_state()
        peer_state = peer.initial_state()
        home_state = home.initial_state()

        issued = self.apply(
            requester,
            requester_state,
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        self.assertEqual(
            {self.TXN_ID: self.NEW_DATA},
            dict(issued.state.make_unique_store_intents),
        )
        initial_line = issued.state.line_at(self.ADDRESS)
        assert initial_line is not None
        self.assertIs(ChiCacheState.I, initial_line.state)
        self.assertIsNone(initial_line.data)

        accepted = self.apply(
            home,
            home_state,
            ChiHomeAcceptMakeUnique(issued.emissions[0]),
        )
        self.assertEqual({self.DBID}, set(accepted.state.pending))
        self.assertFalse(accepted.state.pending[self.DBID].completion_sent)
        self.assertEqual(home_state.backing, accepted.state.backing)
        snoop = accepted.emissions[0]
        self.assertIsInstance(snoop.message, ChiSnpMakeInvalidMessage)
        self.assertEqual(self.PEER, snoop.target_id)

        invalidated = self.apply(
            peer,
            peer_state,
            ChiRnAcceptSnoop(snoop),
        )
        peer_line = invalidated.state.line_at(self.ADDRESS)
        assert peer_line is not None
        self.assertIs(ChiCacheState.I, peer_line.state)
        self.assertIsNone(peer_line.data)
        self.assertIsInstance(
            invalidated.emissions[0].message,
            ChiSnpRespMessage,
        )
        self.assertIs(
            ChiRespCode.I,
            invalidated.emissions[0].message.response,
        )

        collected = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptSnoopResponse(invalidated.emissions[0]),
        )
        completion = collected.emissions[0]
        self.assertIsInstance(completion.message, ChiCompMessage)
        self.assertIs(ChiRespCode.UC, completion.message.response)
        self.assertEqual(self.DBID, completion.message.data_buffer_id)
        self.assertEqual(home_state.backing, collected.state.backing)
        self.assertIsNone(
            collected.state.pending[self.DBID].prepared_backing_write
        )

        completed = self.apply(
            requester,
            issued.state,
            ChiRnAcceptComp(completion),
        )
        requester_line = completed.state.line_at(self.ADDRESS)
        assert requester_line is not None
        self.assertIs(ChiCacheState.UD, requester_line.state)
        self.assertEqual(self.NEW_DATA, requester_line.data)
        self.assertFalse(completed.state.pending_transactions)
        self.assertFalse(completed.state.make_unique_store_intents)
        ack = completed.emissions[0]
        self.assertIsInstance(ack.message, ChiCompAckMessage)
        self.assertEqual(self.DBID, ack.message.transaction_id)

        self.assertIn(self.DBID, collected.state.pending)
        retired = self.apply(
            home,
            collected.state,
            ChiHomeAcceptCompAck(ack),
        )
        entry = retired.state.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        backing = retired.state.backing.line_at(self.ADDRESS)
        assert backing is not None
        self.assertEqual(self.OLD_DATA, backing.data)
        self.assertEqual(0, backing.version)
        self.assertFalse(retired.state.pending)

    def test_make_unique_accepts_all_represented_legal_initial_states(
        self,
    ) -> None:
        absent = build_chi_cache_participant_fixture(
            "absent_requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(),
        )
        absent_issued = self.apply(
            absent,
            absent.initial_state(),
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        self.assertIsNone(absent_issued.state.line_at(self.ADDRESS))

        for state in (
            ChiCacheState.I,
            ChiCacheState.SC,
            ChiCacheState.SD,
            ChiCacheState.UC,
            ChiCacheState.UCE,
        ):
            with self.subTest(state=state):
                requester = self.build_rn(
                    f"requester_{state.value}",
                    self.REQUESTER,
                    state,
                )
                issued = self.apply(
                    requester,
                    requester.initial_state(),
                    ChiRnIssueMakeUnique(
                        self.request(),
                        self.NEW_DATA,
                    ),
                )
                line = issued.state.line_at(self.ADDRESS)
                assert line is not None
                self.assertIs(state, line.state)

        dirty = self.build_rn(
            "dirty_requester",
            self.REQUESTER,
            ChiCacheState.UD,
        )
        rejected = dirty.step(
            dirty.initial_state(),
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        self.assert_fault_rule(rejected, "make_unique_permission")

    def test_pending_make_unique_survives_same_line_make_invalid(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.SD,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        invalidated = self.apply(
            requester,
            issued.state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpMakeInvalidMessage(
                        self.SNOOP_ID,
                        self.ADDRESS,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        line = invalidated.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsInstance(
            invalidated.emissions[0].message,
            ChiSnpRespMessage,
        )
        self.assertEqual(
            {self.TXN_ID: self.NEW_DATA},
            dict(invalidated.state.make_unique_store_intents),
        )

        completed = self.apply(
            requester,
            invalidated.state,
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
        self.assertIs(ChiCacheState.UD, line.state)
        self.assertEqual(self.NEW_DATA, line.data)

    def test_pending_make_unique_sd_returns_data_to_same_line_snp_unique(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.SD,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        snooped = self.apply(
            requester,
            issued.state,
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
        response = snooped.emissions[0].message
        self.assertIsInstance(response, ChiSnpRespDataMessage)
        self.assertIs(ChiRespCode.I_PD, response.response)
        self.assertEqual(self.OLD_DATA, response.data)
        invalid = snooped.state.line_at(self.ADDRESS)
        assert invalid is not None
        self.assertIs(ChiCacheState.I, invalid.state)
        self.assertIsNone(invalid.data)
        self.assertEqual(
            {self.TXN_ID: self.NEW_DATA},
            dict(snooped.state.make_unique_store_intents),
        )

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
        self.assertIs(ChiCacheState.UD, line.state)
        self.assertEqual(self.NEW_DATA, line.data)

    def test_snp_make_invalid_discards_every_represented_holder_state(
        self,
    ) -> None:
        for state in (
            ChiCacheState.I,
            ChiCacheState.SC,
            ChiCacheState.SD,
            ChiCacheState.UC,
            ChiCacheState.UCE,
            ChiCacheState.UD,
        ):
            with self.subTest(state=state):
                peer = self.build_rn(
                    f"peer_{state.value}",
                    self.PEER,
                    state,
                )
                invalidated = self.apply(
                    peer,
                    peer.initial_state(),
                    ChiRnAcceptSnoop(
                        ChiNetworkPacket.snoop(
                            ChiSnpMakeInvalidMessage(
                                self.SNOOP_ID,
                                self.ADDRESS,
                            ),
                            source_id=self.HOME,
                            target_id=self.PEER,
                        )
                    ),
                )
                line = invalidated.state.line_at(self.ADDRESS)
                if line is not None:
                    self.assertIs(ChiCacheState.I, line.state)
                    self.assertIsNone(line.data)
                self.assertNotIn(
                    self.ADDRESS,
                    invalidated.state.cache.lines,
                )
                self.assertIsInstance(
                    invalidated.emissions[0].message,
                    ChiSnpRespMessage,
                )
                self.assertIs(
                    ChiRespCode.I,
                    invalidated.emissions[0].message.response,
                )

    def test_make_unique_rejects_non_full_line_operation_forms(self) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        for request, rule in (
            (self.request(size=5), "make_unique_shape"),
            (
                self.request(expect_completion_ack=False),
                "make_unique_attributes",
            ),
            (
                self.request(tag_operation=1),
                "make_unique_attributes",
            ),
        ):
            with self.subTest(request=request):
                rejected = requester.step(
                    requester.initial_state(),
                    ChiRnIssueMakeUnique(request, self.NEW_DATA),
                )
                self.assert_fault_rule(rejected, rule)

    def test_make_unique_completion_rejects_out_of_slice_forms(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueMakeUnique(self.request(), self.NEW_DATA),
        )
        for changes in (
            {"response_error": ChiRespErr.DERR},
            {"response_error": ChiRespErr.NDERR},
            {"tag_operation": 1},
            {"trace_tag": True},
        ):
            with self.subTest(changes=changes):
                completion = ChiCompMessage(
                    transaction_id=self.TXN_ID,
                    data_buffer_id=self.DBID,
                    response=ChiRespCode.UC,
                    **changes,
                )
                rejected = requester.step(
                    issued.state,
                    ChiRnAcceptComp(
                        ChiNetworkPacket.response(
                            completion,
                            source_id=self.HOME,
                            target_id=self.REQUESTER,
                        )
                    ),
                )
                self.assert_fault_rule(
                    rejected,
                    "make_unique_completion_state",
                )
                self.assertIs(issued.state, rejected.state)

    def test_make_invalid_trace_tag_is_explicitly_out_of_slice(
        self,
    ) -> None:
        peer = self.build_rn("peer", self.PEER, ChiCacheState.UD)
        state = peer.initial_state()
        rejected = peer.step(
            state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpMakeInvalidMessage(
                        self.SNOOP_ID,
                        self.ADDRESS,
                        trace_tag=True,
                    ),
                    source_id=self.HOME,
                    target_id=self.PEER,
                )
            ),
        )
        self.assert_fault_rule(rejected, "snoop_profile")
        self.assertIs(state, rejected.state)

    def test_home_pending_closes_only_after_dataless_i_responses(
        self,
    ) -> None:
        common = {
            "requester_id": self.REQUESTER,
            "request": self.request(),
            "snoop_transaction_id": self.SNOOP_ID,
            "data_buffer_id": self.DBID,
            "snoop_targets": frozenset((self.PEER,)),
        }
        with self.assertRaisesRegex(ValueError, "all selected Snoop"):
            ChiCoherentTransactionPending(
                **common,
                completion_sent=True,
            )
        with self.assertRaisesRegex(ValueError, "data-less SnpResp_I"):
            ChiCoherentTransactionPending(
                **common,
                snoop_results={
                    self.PEER: ChiSnoopResult(
                        ChiRespCode.I,
                        self.OLD_DATA,
                    )
                },
                completion_sent=True,
            )
        with self.assertRaisesRegex(ValueError, "all selected Snoop"):
            ChiCoherentTransactionPending(
                **common,
                snoop_results={
                    self.PEER: ChiSnoopResult(ChiRespCode.I)
                },
                completion_sent=False,
            )
        valid = ChiCoherentTransactionPending(
            **common,
            snoop_results={
                self.PEER: ChiSnoopResult(ChiRespCode.I)
            },
            completion_sent=True,
        )
        self.assertTrue(valid.all_snoops_complete)

    def test_make_unique_home_rejects_snoop_data_even_when_it_is_i(
        self,
    ) -> None:
        home = self.build_home(allow_dirty_data_transfer=True)
        request_packet = ChiNetworkPacket.request(
            self.request(),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )
        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptMakeUnique(request_packet),
        )
        rejected = home.step(
            accepted.state,
            ChiHomeAcceptSnoopResponse(
                ChiNetworkPacket.data(
                    ChiSnpRespDataMessage(
                        transaction_id=self.SNOOP_ID,
                        data=self.OLD_DATA,
                        response=ChiRespCode.I,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(rejected, "snoop_response_state")
        traced = home.step(
            accepted.state,
            ChiHomeAcceptSnoopResponse(
                ChiNetworkPacket.response(
                    ChiSnpRespMessage(
                        transaction_id=self.SNOOP_ID,
                        response=ChiRespCode.I,
                        trace_tag=True,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(traced, "make_unique_snoop_trace")
        self.assertIs(accepted.state, traced.state)


if __name__ == "__main__":
    unittest.main()
