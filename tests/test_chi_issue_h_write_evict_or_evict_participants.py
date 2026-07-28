from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptCopyBackData,
    ChiHomeAcceptWriteEvictOrEvict,
    ChiHomeDirectoryEntry,
    ChiHomeWriteEvictOrEvictPending,
    ChiRnAcceptComp,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptSnoop,
    ChiRnCopyBackOutcome,
    ChiRnIssueWriteEvictOrEvict,
    ChiRnWriteEvictOrEvictPending,
    ChiWriteEvictOrEvictDecision,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiNetworkPacket,
    ChiRespCode,
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpRespDataMessage,
    ChiSnpUniqueMessage,
    ChiWriteEvictOrEvictMessage,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
    FullLineBackingCore,
)


class ChiIssueHWriteEvictOrEvictParticipantTest(unittest.TestCase):
    RN = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0x42
    TXN_ID = 0x142
    DBID = 0x242

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_atomic_fault(self, transition, state, suffix: str) -> None:
        self.assertIsNotNone(transition.fault)
        self.assertTrue(transition.fault.rule.endswith(suffix))
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

    def build_rn(self, state: ChiCacheState):
        return build_chi_cache_participant_fixture(
            "weoe_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                ChiCacheLine(self.ADDRESS, state, self.DATA),
            ),
        )

    def build_home(
        self,
        *,
        shared: bool,
        decision: ChiWriteEvictOrEvictDecision,
        shared_dirty_owner: int | None = None,
        clean_residency: bool = True,
    ) -> ChiCoherentHomeNode:
        entry = (
            ChiHomeDirectoryEntry(
                self.ADDRESS,
                sharers=frozenset((self.RN, self.PEER)),
                shared_dirty_owner=shared_dirty_owner,
            )
            if shared
            else ChiHomeDirectoryEntry(
                self.ADDRESS,
                unique_owner=self.RN,
            )
        )
        return ChiCoherentHomeNode(
            "weoe_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "weoe_home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(entry,),
            clean_residency_core=(
                CacheCore(
                    "weoe_home.clean",
                    CacheLineStore(
                        "weoe_home.clean.lines",
                        line_bytes=64,
                    ),
                )
                if clean_residency
                else None
            ),
            initial_data_buffer_id=self.DBID,
            write_evict_or_evict_policy=(
                lambda _request, _state: decision
            ),
        )

    def request(self, state: ChiCacheState):
        return ChiWriteEvictOrEvictMessage(
            self.TXN_ID,
            self.ADDRESS,
            likely_shared=state is ChiCacheState.SC,
        )

    def start(
        self,
        state: ChiCacheState,
        decision: ChiWriteEvictOrEvictDecision,
        *,
        shared_dirty_owner: int | None = None,
        clean_residency: bool = True,
    ):
        rn = self.build_rn(state)
        home = self.build_home(
            shared=state is ChiCacheState.SC,
            decision=decision,
            shared_dirty_owner=shared_dirty_owner,
            clean_residency=clean_residency,
        )
        rn_initial = rn.initial_state()
        home_initial = home.initial_state()
        issued = self.apply(
            rn,
            rn_initial,
            ChiRnIssueWriteEvictOrEvict(self.request(state)),
        )
        accepted = self.apply(
            home,
            home_initial,
            ChiHomeAcceptWriteEvictOrEvict(issued.emissions[0]),
        )
        return rn, home, rn_initial, home_initial, issued, accepted

    def test_data_branch_covers_uc_and_clean_sc(self) -> None:
        for initial_state in (ChiCacheState.UC, ChiCacheState.SC):
            with self.subTest(initial_state=initial_state):
                (
                    rn,
                    home,
                    _rn_initial,
                    home_initial,
                    issued,
                    accepted,
                ) = self.start(
                    initial_state,
                    ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                )
                pending = issued.state.pending_copybacks[self.TXN_ID]
                self.assertIsInstance(
                    pending,
                    ChiRnWriteEvictOrEvictPending,
                )
                self.assertIs(
                    (
                        ChiRnCopyBackOutcome.LIVE_SC
                        if initial_state is ChiCacheState.SC
                        else ChiRnCopyBackOutcome.LIVE_UC
                    ),
                    pending.outcome,
                )
                response_packet = accepted.emissions[0]
                self.assertIsInstance(
                    response_packet.message,
                    ChiCompDBIDRespMessage,
                )
                home_pending = accepted.state.pending_copybacks[self.DBID]
                self.assertIsInstance(
                    home_pending,
                    ChiHomeWriteEvictOrEvictPending,
                )
                self.assertIs(
                    ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                    home_pending.decision,
                )

                copied = self.apply(
                    rn,
                    issued.state,
                    ChiRnAcceptCompDBIDResp(response_packet),
                )
                copyback_packet = copied.emissions[0]
                copyback = copyback_packet.message
                self.assertIsInstance(
                    copyback,
                    ChiCopyBackWrDataMessage,
                )
                self.assertIs(
                    (
                        ChiRespCode.SC
                        if initial_state is ChiCacheState.SC
                        else ChiRespCode.UC
                    ),
                    copyback.response,
                )
                self.assertEqual(self.DATA, copyback.data)
                self.assertEqual((1 << 64) - 1, copyback.byte_enable)
                self.assertIs(
                    ChiCacheState.I,
                    copied.state.line_at(self.ADDRESS).state,
                )

                committed = self.apply(
                    home,
                    accepted.state,
                    ChiHomeAcceptCopyBackData(copyback_packet),
                )
                entry = committed.state.directory[self.ADDRESS]
                self.assertNotEqual(self.RN, entry.unique_owner)
                self.assertNotIn(self.RN, entry.sharers)
                if initial_state is ChiCacheState.SC:
                    self.assertEqual(
                        frozenset((self.PEER,)),
                        entry.sharers,
                    )
                resident = committed.state.clean_residency.line_at(
                    self.ADDRESS
                )
                self.assertIsInstance(resident, CacheLinePayload)
                self.assertEqual(self.DATA, resident.data)
                self.assertIs(
                    home_initial.backing,
                    committed.state.backing,
                )
                self.assertTrue(rn.is_quiescent(copied.state))
                self.assertTrue(home.is_quiescent(committed.state))

    def test_no_data_branch_uses_stateful_comp_ack(self) -> None:
        for initial_state in (ChiCacheState.UC, ChiCacheState.SC):
            with self.subTest(initial_state=initial_state):
                (
                    rn,
                    home,
                    _rn_initial,
                    home_initial,
                    issued,
                    accepted,
                ) = self.start(
                    initial_state,
                    ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
                    shared_dirty_owner=(
                        self.PEER
                        if initial_state is ChiCacheState.SC
                        else None
                    ),
                    clean_residency=False,
                )
                completion_packet = accepted.emissions[0]
                completion = completion_packet.message
                self.assertIsInstance(completion, ChiCompMessage)
                self.assertIs(ChiRespCode.I, completion.response)
                self.assertEqual(self.DBID, completion.data_buffer_id)

                completed = self.apply(
                    rn,
                    issued.state,
                    ChiRnAcceptComp(completion_packet),
                )
                ack_packet = completed.emissions[0]
                ack = ack_packet.message
                self.assertIsInstance(ack, ChiCompAckMessage)
                self.assertEqual(self.DBID, ack.transaction_id)
                self.assertEqual(
                    int(
                        ChiRespCode.SC
                        if initial_state is ChiCacheState.SC
                        else ChiRespCode.UC
                    ),
                    ack.response,
                )
                self.assertIs(
                    ChiCacheState.I,
                    completed.state.line_at(self.ADDRESS).state,
                )

                retired = self.apply(
                    home,
                    accepted.state,
                    ChiHomeAcceptCompAck(ack_packet),
                )
                entry = retired.state.directory[self.ADDRESS]
                self.assertNotEqual(self.RN, entry.unique_owner)
                self.assertNotIn(self.RN, entry.sharers)
                if initial_state is ChiCacheState.SC:
                    self.assertEqual(
                        frozenset((self.PEER,)),
                        entry.sharers,
                    )
                    self.assertEqual(self.PEER, entry.shared_dirty_owner)
                self.assertFalse(retired.state.clean_residency.lines)
                self.assertIs(home_initial.backing, retired.state.backing)
                self.assertTrue(rn.is_quiescent(completed.state))
                self.assertTrue(home.is_quiescent(retired.state))

    def test_likely_shared_must_match_resident_state(self) -> None:
        rn = self.build_rn(ChiCacheState.SC)
        initial = rn.initial_state()
        mismatch = ChiWriteEvictOrEvictMessage(
            self.TXN_ID,
            self.ADDRESS,
            likely_shared=False,
        )

        transition = rn.step(
            initial,
            ChiRnIssueWriteEvictOrEvict(mismatch),
        )

        self.assert_atomic_fault(
            transition,
            initial,
            "write_evict_or_evict_permission",
        )

    def test_data_policy_rejects_sc_with_shared_dirty_peer(self) -> None:
        rn = self.build_rn(ChiCacheState.SC)
        home = self.build_home(
            shared=True,
            decision=ChiWriteEvictOrEvictDecision.REQUEST_DATA,
            shared_dirty_owner=self.PEER,
        )
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteEvictOrEvict(
                self.request(ChiCacheState.SC)
            ),
        )
        initial = home.initial_state()

        transition = home.step(
            initial,
            ChiHomeAcceptWriteEvictOrEvict(issued.emissions[0]),
        )

        self.assert_atomic_fault(
            transition,
            initial,
            "write_evict_or_evict_shared_dirty_data",
        )

    def test_direct_home_requires_an_explicit_outcome_policy(self) -> None:
        rn = self.build_rn(ChiCacheState.UC)
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteEvictOrEvict(
                self.request(ChiCacheState.UC)
            ),
        )
        home = ChiCoherentHomeNode(
            "weoe_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "weoe_home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.RN,
                ),
            ),
            clean_residency_core=CacheCore(
                "weoe_home.clean",
                CacheLineStore(
                    "weoe_home.clean.lines",
                    line_bytes=64,
                ),
            ),
        )
        initial = home.initial_state()

        transition = home.step(
            initial,
            ChiHomeAcceptWriteEvictOrEvict(issued.emissions[0]),
        )

        self.assert_atomic_fault(
            transition,
            initial,
            "write_evict_or_evict_policy",
        )

    def test_home_selected_terminal_is_not_interchangeable(self) -> None:
        (
            _rn,
            data_home,
            _rn_initial,
            _home_initial,
            _issued,
            data_accepted,
        ) = self.start(
            ChiCacheState.UC,
            ChiWriteEvictOrEvictDecision.REQUEST_DATA,
        )
        forged_ack = ChiNetworkPacket.response(
            ChiCompAckMessage(
                self.DBID,
                response=ChiRespCode.UC,
            ),
            source_id=self.RN,
            target_id=self.HOME,
        )
        wrong_ack = data_home.step(
            data_accepted.state,
            ChiHomeAcceptCompAck(forged_ack),
        )
        self.assert_atomic_fault(
            wrong_ack,
            data_accepted.state,
            "write_evict_or_evict_terminal",
        )

        (
            _rn,
            no_data_home,
            _rn_initial,
            _home_initial,
            _issued,
            no_data_accepted,
        ) = self.start(
            ChiCacheState.UC,
            ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
            clean_residency=False,
        )
        forged_data = ChiNetworkPacket.data(
            ChiCopyBackWrDataMessage(
                self.DBID,
                self.DATA,
                response=ChiRespCode.UC,
            ),
            source_id=self.RN,
            target_id=self.HOME,
        )
        wrong_data = no_data_home.step(
            no_data_accepted.state,
            ChiHomeAcceptCopyBackData(forged_data),
        )
        self.assert_atomic_fault(
            wrong_data,
            no_data_accepted.state,
            "write_evict_or_evict_terminal",
        )

    def test_pre_response_invalidating_snoop_cancels_both_terminal_flows(
        self,
    ) -> None:
        snoop_types = (
            ChiSnpUniqueMessage,
            ChiSnpCleanInvalidMessage,
            ChiSnpMakeInvalidMessage,
        )
        response_types = (
            ChiCompDBIDRespMessage,
            ChiCompMessage,
        )
        for initial_state in (ChiCacheState.UC, ChiCacheState.SC):
            for snoop_type in snoop_types:
                for response_type in response_types:
                    with self.subTest(
                        initial_state=initial_state.value,
                        snoop=snoop_type.__name__,
                        response=response_type.__name__,
                    ):
                        rn = self.build_rn(initial_state)
                        issued = self.apply(
                            rn,
                            rn.initial_state(),
                            ChiRnIssueWriteEvictOrEvict(
                                self.request(initial_state)
                            ),
                        )
                        snooped = self.apply(
                            rn,
                            issued.state,
                            ChiRnAcceptSnoop(
                                ChiNetworkPacket.snoop(
                                    snoop_type(0x300, self.ADDRESS),
                                    source_id=self.HOME,
                                    target_id=self.RN,
                                )
                            ),
                        )

                        line = snooped.state.line_at(self.ADDRESS)
                        self.assertIsNotNone(line)
                        assert line is not None
                        self.assertIs(ChiCacheState.I, line.state)
                        self.assertIsNone(line.data)
                        self.assertNotIn(
                            self.ADDRESS,
                            snooped.state.cache.lines,
                        )
                        pending = snooped.state.pending_copybacks[
                            self.TXN_ID
                        ]
                        self.assertEqual(
                            issued.state.pending_copybacks[
                                self.TXN_ID
                            ].request,
                            pending.request,
                        )
                        self.assertIs(
                            ChiRnCopyBackOutcome.CANCELED_I,
                            pending.outcome,
                        )
                        self.assertEqual(1, len(snooped.emissions))
                        self.assertIs(
                            ChiRespCode.I,
                            snooped.emissions[0].message.response,
                        )

                        response = (
                            ChiCompDBIDRespMessage(
                                self.TXN_ID,
                                self.DBID,
                            )
                            if response_type
                            is ChiCompDBIDRespMessage
                            else ChiCompMessage(
                                self.TXN_ID,
                                self.DBID,
                                response=ChiRespCode.I,
                            )
                        )
                        completed = self.apply(
                            rn,
                            snooped.state,
                            (
                                ChiRnAcceptCompDBIDResp(
                                    ChiNetworkPacket.response(
                                        response,
                                        source_id=self.HOME,
                                        target_id=self.RN,
                                    )
                                )
                                if response_type
                                is ChiCompDBIDRespMessage
                                else ChiRnAcceptComp(
                                    ChiNetworkPacket.response(
                                        response,
                                        source_id=self.HOME,
                                        target_id=self.RN,
                                    )
                                )
                            ),
                        )

                        self.assertFalse(
                            completed.state.pending_copybacks
                        )
                        terminal = completed.emissions[0].message
                        if isinstance(
                            terminal,
                            ChiCopyBackWrDataMessage,
                        ):
                            self.assertIs(
                                ChiRespCode.I,
                                terminal.response,
                            )
                            self.assertEqual(0, terminal.data)
                            self.assertEqual(0, terminal.byte_enable)
                        else:
                            self.assertIsInstance(
                                terminal,
                                ChiCompAckMessage,
                            )
                            self.assertEqual(
                                int(ChiRespCode.I),
                                terminal.response,
                            )

    def test_pre_response_snp_unique_can_return_clean_payload_then_cancel(
        self,
    ) -> None:
        rn = self.build_rn(ChiCacheState.SC)
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteEvictOrEvict(
                self.request(ChiCacheState.SC)
            ),
        )

        snooped = self.apply(
            rn,
            issued.state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpUniqueMessage(
                        0x301,
                        self.ADDRESS,
                        return_to_source=True,
                    ),
                    source_id=self.HOME,
                    target_id=self.RN,
                )
            ),
        )

        response = snooped.emissions[0].message
        self.assertIsInstance(response, ChiSnpRespDataMessage)
        self.assertIs(ChiRespCode.I, response.response)
        self.assertEqual(self.DATA, response.data)
        self.assertIs(
            ChiRnCopyBackOutcome.CANCELED_I,
            snooped.state.pending_copybacks[self.TXN_ID].outcome,
        )

    def test_multiple_pre_response_snoops_preserve_canceled_terminal(
        self,
    ) -> None:
        rn = self.build_rn(ChiCacheState.SC)
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteEvictOrEvict(
                self.request(ChiCacheState.SC)
            ),
        )

        state = issued.state
        for snoop in (
            ChiSnpUniqueMessage(0x302, self.ADDRESS),
            ChiSnpCleanInvalidMessage(0x303, self.ADDRESS),
        ):
            snooped = self.apply(
                rn,
                state,
                ChiRnAcceptSnoop(
                    ChiNetworkPacket.snoop(
                        snoop,
                        source_id=self.HOME,
                        target_id=self.RN,
                    )
                ),
            )
            self.assertEqual(1, len(snooped.emissions))
            response = snooped.emissions[0].message
            self.assertIs(ChiRespCode.I, response.response)
            self.assertEqual(
                snoop.transaction_id,
                response.transaction_id,
            )
            self.assertIs(
                ChiRnCopyBackOutcome.CANCELED_I,
                snooped.state.pending_copybacks[
                    self.TXN_ID
                ].outcome,
            )
            state = snooped.state

        completed = self.apply(
            rn,
            state,
            ChiRnAcceptCompDBIDResp(
                ChiNetworkPacket.response(
                    ChiCompDBIDRespMessage(
                        self.TXN_ID,
                        self.DBID,
                    ),
                    source_id=self.HOME,
                    target_id=self.RN,
                )
            ),
        )
        self.assertFalse(completed.state.pending_copybacks)
        terminal = completed.emissions[0].message
        self.assertIsInstance(terminal, ChiCopyBackWrDataMessage)
        self.assertIs(ChiRespCode.I, terminal.response)
        self.assertEqual(0, terminal.data)
        self.assertEqual(0, terminal.byte_enable)


if __name__ == "__main__":
    unittest.main()
