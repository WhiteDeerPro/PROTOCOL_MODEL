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
    ChiCoherentTransactionPending,
    ChiCopyBackDecision,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptCopyBackData,
    ChiHomeAcceptCoherentRead,
    ChiHomeAcceptWriteEvictFull,
    ChiHomeCopyBackAdmission,
    ChiHomeDirectoryEntry,
    ChiHomeWriteEvictPending,
    ChiRnAcceptComp,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptCompData,
    ChiRnAcceptSnoop,
    ChiRnCopyBackOutcome,
    ChiRnIssueCoherentRead,
    ChiRnIssueWriteEvictFull,
    ChiRnWriteCacheLine,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiNetworkPacket,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpRespMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
    ChiWriteEvictFullMessage,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
    CacheLineStoreState,
    FullLineBackingCore,
)


class ChiIssueHWriteEvictFullCopyAtHomeParticipantTest(
    unittest.TestCase
):
    RN = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xCA11_600D
    UPDATED_DATA = DATA ^ 0x55
    READ_TXN_ID = 0x11A
    WRITE_EVICT_TXN_ID = 0x11B
    DBID = 0x220

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

    def build_rn(
        self,
        *,
        resident: bool = True,
        copy_at_home: bool = False,
    ):
        return build_chi_cache_participant_fixture(
            "copy_at_home_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                (
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.UC,
                        self.DATA,
                        copy_at_home=copy_at_home,
                    ),
                )
                if resident
                else ()
            ),
        )

    def build_home(
        self,
        decision: ChiCopyBackDecision,
        *,
        read_copy_at_home_policy=None,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "copy_at_home_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "copy_at_home_home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(ChiHomeDirectoryEntry(self.ADDRESS),),
            clean_residency_core=CacheCore(
                "copy_at_home_home.clean",
                CacheLineStore(
                    "copy_at_home_home.clean.lines",
                    line_bytes=64,
                    initial_lines=(
                        CacheLinePayload(self.ADDRESS, self.DATA),
                    ),
                ),
            ),
            initial_data_buffer_id=self.DBID,
            read_unique_copy_at_home_policy=read_copy_at_home_policy,
            write_evict_full_current_copy_policy=(
                lambda _request, _state: decision
            ),
        )

    def acquire_copy_at_home(
        self,
        decision: ChiCopyBackDecision,
    ):
        policy_calls: list[int] = []

        def retain_existing_clean_copy(request, state):
            policy_calls.append(request.address)
            return (
                state.clean_residency.line_at(request.address) is not None
            )

        rn = self.build_rn(resident=False)
        home = self.build_home(
            decision,
            read_copy_at_home_policy=retain_existing_clean_copy,
        )
        rn_initial = rn.initial_state()
        home_initial = home.initial_state()
        self.assertEqual(
            self.DATA,
            home_initial.clean_residency.line_at(self.ADDRESS).data,
        )

        read_issued = self.apply(
            rn,
            rn_initial,
            ChiRnIssueCoherentRead(
                ChiReadUniqueMessage(self.READ_TXN_ID, self.ADDRESS)
            ),
        )
        read_accepted = self.apply(
            home,
            home_initial,
            ChiHomeAcceptCoherentRead(read_issued.emissions[0]),
        )
        completion_packet = read_accepted.emissions[0]
        completion = completion_packet.message
        self.assertIsInstance(completion, ChiCompDataMessage)
        self.assertTrue(completion.copy_at_home)
        self.assertIs(ChiRespCode.UC, completion.response)
        self.assertEqual(self.DATA, completion.data)
        self.assertEqual([self.ADDRESS], policy_calls)

        read_completed = self.apply(
            rn,
            read_issued.state,
            ChiRnAcceptCompData(completion_packet),
        )
        line = read_completed.state.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.UC, line.state)
        self.assertTrue(line.copy_at_home)
        self.assertIn(
            self.ADDRESS,
            read_completed.state.copy_at_home_lines,
        )

        read_committed = self.apply(
            home,
            read_accepted.state,
            ChiHomeAcceptCompAck(read_completed.emissions[0]),
        )
        self.assertEqual(
            self.RN,
            read_committed.state.directory[
                self.ADDRESS
            ].unique_owner,
        )
        self.assertEqual(
            self.DATA,
            read_committed.state.clean_residency.line_at(
                self.ADDRESS
            ).data,
        )
        return (
            rn,
            home,
            read_completed.state,
            read_committed.state,
        )

    def start_write_evict(
        self,
        decision: ChiCopyBackDecision,
    ):
        rn, home, rn_state, home_state = self.acquire_copy_at_home(
            decision
        )
        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )
        issued = self.apply(
            rn,
            rn_state,
            ChiRnIssueWriteEvictFull(request),
        )
        accepted = self.apply(
            home,
            home_state,
            ChiHomeAcceptWriteEvictFull(issued.emissions[0]),
        )
        return rn, home, rn_state, home_state, issued, accepted

    def assert_retired_clean_victim(self, rn_state, home_state) -> None:
        line = rn_state.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertFalse(line.copy_at_home)
        self.assertNotIn(self.ADDRESS, rn_state.cache.lines)
        self.assertNotIn(self.ADDRESS, rn_state.copy_at_home_lines)
        self.assertFalse(rn_state.pending_copybacks)

        entry = home_state.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        self.assertFalse(home_state.pending_copybacks)
        backing = home_state.backing.line_at(self.ADDRESS)
        residency = home_state.clean_residency.line_at(self.ADDRESS)
        self.assertIsNotNone(backing)
        self.assertIsNotNone(residency)
        assert backing is not None
        assert residency is not None
        self.assertEqual(self.DATA, backing.data)
        self.assertEqual(0, backing.version)
        self.assertEqual(self.DATA, residency.data)

    def test_initial_provenance_readout_and_local_write_clear(self) -> None:
        rn = self.build_rn(copy_at_home=True)
        initial = rn.initial_state()

        line = initial.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.UC, line.state)
        self.assertTrue(line.copy_at_home)
        self.assertEqual(
            frozenset((self.ADDRESS,)),
            initial.copy_at_home_lines,
        )

        written = self.apply(
            rn,
            initial,
            ChiRnWriteCacheLine(self.ADDRESS, self.UPDATED_DATA),
        )
        line = written.state.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.UD, line.state)
        self.assertEqual(self.UPDATED_DATA, line.data)
        self.assertFalse(line.copy_at_home)
        self.assertFalse(written.state.copy_at_home_lines)

    def test_home_copy_at_home_pending_rejects_peer_snoop_state(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "no peer Snoop"):
            ChiCoherentTransactionPending(
                self.RN,
                ChiReadUniqueMessage(self.READ_TXN_ID, self.ADDRESS),
                0x100,
                self.DBID,
                frozenset((0x08,)),
                copy_at_home=True,
            )

    def test_home_copy_at_home_pending_protects_clean_residency(
        self,
    ) -> None:
        rn = self.build_rn(resident=False)
        home = self.build_home(
            ChiCopyBackDecision.REQUEST_DATA,
            read_copy_at_home_policy=lambda _request, _state: True,
        )
        read_issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueCoherentRead(
                ChiReadUniqueMessage(self.READ_TXN_ID, self.ADDRESS)
            ),
        )
        read_accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCoherentRead(read_issued.emissions[0]),
        )

        with self.assertRaisesRegex(
            ValueError,
            "protected clean residency",
        ):
            replace(
                read_accepted.state,
                clean_residency=CacheLineStoreState(),
            )

    def test_shared_holder_pending_requires_clean_requester_snapshot(
        self,
    ) -> None:
        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )
        invalid_snapshots = (
            ChiHomeDirectoryEntry(
                self.ADDRESS,
                unique_owner=self.RN,
            ),
            ChiHomeDirectoryEntry(
                self.ADDRESS,
                sharers=frozenset((self.RN,)),
                shared_dirty_owner=self.RN,
            ),
        )
        for snapshot in invalid_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaisesRegex(
                    ValueError,
                    "requires a clean requester",
                ):
                    ChiHomeWriteEvictPending(
                        self.RN,
                        request,
                        self.DBID,
                        snapshot,
                        0,
                        admission=(
                            ChiHomeCopyBackAdmission.CURRENT_SHARED_HOLDER
                        ),
                    )

        snapshot = ChiHomeDirectoryEntry(
            self.ADDRESS,
            sharers=frozenset((self.RN, self.PEER)),
        )
        pending = ChiHomeWriteEvictPending(
            self.RN,
            request,
            self.DBID,
            snapshot,
            0,
            admission=ChiHomeCopyBackAdmission.CURRENT_SHARED_HOLDER,
        )
        self.assertEqual(snapshot, pending.directory_snapshot)
        self.assertIs(
            ChiHomeCopyBackAdmission.CURRENT_SHARED_HOLDER,
            pending.admission,
        )

    def test_forged_copy_at_home_issue_is_atomic_fault(self) -> None:
        rn = self.build_rn(copy_at_home=False)
        initial = rn.initial_state()

        rejected = rn.step(
            initial,
            ChiRnIssueWriteEvictFull(
                ChiWriteEvictFullMessage(
                    self.WRITE_EVICT_TXN_ID,
                    self.ADDRESS,
                    copy_at_home=True,
                )
            ),
        )

        self.assert_atomic_fault(
            rejected,
            initial,
            "write_evict_copy_at_home_provenance",
        )

    def test_home_comp_data_establishes_cached_provenance(self) -> None:
        _, _, rn_state, home_state = self.acquire_copy_at_home(
            ChiCopyBackDecision.REQUEST_DATA
        )

        self.assertTrue(
            rn_state.line_at(self.ADDRESS).copy_at_home
        )
        self.assertEqual(
            self.RN,
            home_state.directory[self.ADDRESS].unique_owner,
        )
        self.assertEqual(
            self.DATA,
            home_state.clean_residency.line_at(self.ADDRESS).data,
        )

    def test_invalidating_snoop_then_shared_stays_canceled_for_both_terminals(
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
        for snoop_type in snoop_types:
            for response_type in response_types:
                with self.subTest(
                    snoop=snoop_type.__name__,
                    response=response_type.__name__,
                ):
                    rn = self.build_rn(copy_at_home=True)
                    issued = self.apply(
                        rn,
                        rn.initial_state(),
                        ChiRnIssueWriteEvictFull(
                            ChiWriteEvictFullMessage(
                                self.WRITE_EVICT_TXN_ID,
                                self.ADDRESS,
                                copy_at_home=True,
                            )
                        ),
                    )
                    frozen_request = issued.state.pending_copybacks[
                        self.WRITE_EVICT_TXN_ID
                    ].request
                    self.assertTrue(frozen_request.copy_at_home)

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
                    self.assertFalse(line.copy_at_home)
                    self.assertNotIn(
                        self.ADDRESS,
                        snooped.state.cache.lines,
                    )
                    self.assertNotIn(
                        self.ADDRESS,
                        snooped.state.copy_at_home_lines,
                    )
                    pending = snooped.state.pending_copybacks[
                        self.WRITE_EVICT_TXN_ID
                    ]
                    self.assertEqual(frozen_request, pending.request)
                    self.assertTrue(pending.request.copy_at_home)
                    self.assertIs(
                        ChiRnCopyBackOutcome.CANCELED_I,
                        pending.outcome,
                    )
                    self.assertEqual(1, len(snooped.emissions))
                    snoop_response = snooped.emissions[0].message
                    self.assertIsInstance(
                        snoop_response,
                        ChiSnpRespMessage,
                    )
                    self.assertIs(
                        ChiRespCode.I,
                        snoop_response.response,
                    )

                    shared_after_cancel = self.apply(
                        rn,
                        snooped.state,
                        ChiRnAcceptSnoop(
                            ChiNetworkPacket.snoop(
                                ChiSnpSharedMessage(
                                    0x301,
                                    self.ADDRESS,
                                ),
                                source_id=self.HOME,
                                target_id=self.RN,
                            )
                        ),
                    )
                    line = shared_after_cancel.state.line_at(
                        self.ADDRESS
                    )
                    self.assertIsNotNone(line)
                    assert line is not None
                    self.assertIs(ChiCacheState.I, line.state)
                    self.assertIsNone(line.data)
                    pending = (
                        shared_after_cancel.state.pending_copybacks[
                            self.WRITE_EVICT_TXN_ID
                        ]
                    )
                    self.assertEqual(frozen_request, pending.request)
                    self.assertIs(
                        ChiRnCopyBackOutcome.CANCELED_I,
                        pending.outcome,
                    )
                    shared_response = (
                        shared_after_cancel.emissions[0].message
                    )
                    self.assertIsInstance(
                        shared_response,
                        ChiSnpRespMessage,
                    )
                    self.assertIs(
                        ChiRespCode.I,
                        shared_response.response,
                    )

                    response = (
                        ChiCompDBIDRespMessage(
                            self.WRITE_EVICT_TXN_ID,
                            self.DBID,
                        )
                        if response_type is ChiCompDBIDRespMessage
                        else ChiCompMessage(
                            self.WRITE_EVICT_TXN_ID,
                            self.DBID,
                            response=ChiRespCode.I,
                        )
                    )
                    completed = self.apply(
                        rn,
                        shared_after_cancel.state,
                        (
                            ChiRnAcceptCompDBIDResp(
                                ChiNetworkPacket.response(
                                    response,
                                    source_id=self.HOME,
                                    target_id=self.RN,
                                )
                            )
                            if response_type is ChiCompDBIDRespMessage
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
                    if isinstance(terminal, ChiCopyBackWrDataMessage):
                        self.assertIs(ChiRespCode.I, terminal.response)
                        self.assertEqual(0, terminal.data)
                        self.assertEqual(0, terminal.byte_enable)
                    else:
                        self.assertIsInstance(terminal, ChiCompAckMessage)
                        self.assertEqual(
                            int(ChiRespCode.I),
                            terminal.response,
                        )

    def test_pre_response_snp_shared_preserves_sc_terminals(
        self,
    ) -> None:
        for copy_at_home, decision in (
            (False, ChiCopyBackDecision.REQUEST_DATA),
            (True, ChiCopyBackDecision.REQUEST_DATA),
            (True, ChiCopyBackDecision.COMPLETE_WITHOUT_DATA),
        ):
            with self.subTest(
                copy_at_home=copy_at_home,
                decision=decision.value,
            ):
                rn = self.build_rn(copy_at_home=copy_at_home)
                home = self.build_home(decision)
                rn_initial = rn.initial_state()
                home_after_read_shared = replace(
                    home.initial_state(),
                    directory={
                        self.ADDRESS: ChiHomeDirectoryEntry(
                            self.ADDRESS,
                            sharers=frozenset((self.RN, self.PEER)),
                        )
                    },
                )
                request = ChiWriteEvictFullMessage(
                    self.WRITE_EVICT_TXN_ID,
                    self.ADDRESS,
                    copy_at_home=copy_at_home,
                )
                issued = self.apply(
                    rn,
                    rn_initial,
                    ChiRnIssueWriteEvictFull(request),
                )
                snooped = self.apply(
                    rn,
                    issued.state,
                    ChiRnAcceptSnoop(
                        ChiNetworkPacket.snoop(
                            ChiSnpSharedMessage(0x300, self.ADDRESS),
                            source_id=self.HOME,
                            target_id=self.RN,
                        )
                    ),
                )

                snoop_response = snooped.emissions[0].message
                self.assertIsInstance(
                    snoop_response,
                    ChiSnpRespMessage,
                )
                self.assertIs(
                    ChiRespCode.SC,
                    snoop_response.response,
                )
                line = snooped.state.line_at(self.ADDRESS)
                self.assertIsNotNone(line)
                assert line is not None
                self.assertIs(ChiCacheState.SC, line.state)
                self.assertEqual(self.DATA, line.data)
                self.assertFalse(line.copy_at_home)
                self.assertNotIn(
                    self.ADDRESS,
                    snooped.state.copy_at_home_lines,
                )
                pending = snooped.state.pending_copybacks[
                    self.WRITE_EVICT_TXN_ID
                ]
                self.assertEqual(request, pending.request)
                self.assertIs(
                    copy_at_home,
                    pending.request.copy_at_home,
                )
                self.assertIs(
                    ChiRnCopyBackOutcome.LIVE_SC,
                    pending.outcome,
                )

                accepted = self.apply(
                    home,
                    home_after_read_shared,
                    ChiHomeAcceptWriteEvictFull(
                        issued.emissions[0],
                        admission=(
                            ChiHomeCopyBackAdmission.CURRENT_SHARED_HOLDER
                        ),
                    ),
                )
                home_response = accepted.emissions[0]
                if decision is ChiCopyBackDecision.REQUEST_DATA:
                    self.assertIsInstance(
                        home_response.message,
                        ChiCompDBIDRespMessage,
                    )
                    completed = self.apply(
                        rn,
                        snooped.state,
                        ChiRnAcceptCompDBIDResp(home_response),
                    )
                    terminal_packet = completed.emissions[0]
                    terminal = terminal_packet.message
                    self.assertIsInstance(
                        terminal,
                        ChiCopyBackWrDataMessage,
                    )
                    self.assertIs(ChiRespCode.SC, terminal.response)
                    self.assertEqual(self.DATA, terminal.data)
                    self.assertEqual(
                        (1 << 64) - 1,
                        terminal.byte_enable,
                    )
                    forged_packet = replace(
                        terminal_packet,
                        message=replace(
                            terminal,
                            response=ChiRespCode.UC,
                        ),
                    )
                    rejected = home.step(
                        accepted.state,
                        ChiHomeAcceptCopyBackData(forged_packet),
                    )
                    self.assert_atomic_fault(
                        rejected,
                        accepted.state,
                        "write_evict_copyback_profile",
                    )
                    committed = self.apply(
                        home,
                        accepted.state,
                        ChiHomeAcceptCopyBackData(terminal_packet),
                    )
                else:
                    self.assertIsInstance(
                        home_response.message,
                        ChiCompMessage,
                    )
                    completed = self.apply(
                        rn,
                        snooped.state,
                        ChiRnAcceptComp(home_response),
                    )
                    terminal_packet = completed.emissions[0]
                    terminal = terminal_packet.message
                    self.assertIsInstance(terminal, ChiCompAckMessage)
                    self.assertEqual(
                        int(ChiRespCode.SC),
                        terminal.response,
                    )
                    forged_packet = replace(
                        terminal_packet,
                        message=replace(
                            terminal,
                            response=ChiRespCode.UC,
                        ),
                    )
                    rejected = home.step(
                        accepted.state,
                        ChiHomeAcceptCompAck(forged_packet),
                    )
                    self.assert_atomic_fault(
                        rejected,
                        accepted.state,
                        "write_evict_completion_ack_state",
                    )
                    committed = self.apply(
                        home,
                        accepted.state,
                        ChiHomeAcceptCompAck(terminal_packet),
                    )

                retired_line = completed.state.line_at(self.ADDRESS)
                self.assertIsNotNone(retired_line)
                assert retired_line is not None
                self.assertIs(ChiCacheState.I, retired_line.state)
                self.assertIsNone(retired_line.data)
                self.assertFalse(retired_line.copy_at_home)
                self.assertFalse(completed.state.pending_copybacks)
                self.assertTrue(rn.is_quiescent(completed.state))

                entry = committed.state.directory[self.ADDRESS]
                self.assertIsNone(entry.unique_owner)
                self.assertEqual(
                    frozenset((self.PEER,)),
                    entry.sharers,
                )
                self.assertIsNone(entry.shared_dirty_owner)
                self.assertEqual(
                    self.DATA,
                    committed.state.clean_residency.line_at(
                        self.ADDRESS
                    ).data,
                )
                self.assertIs(
                    home_after_read_shared.backing,
                    committed.state.backing,
                )
                self.assertFalse(committed.state.pending_copybacks)
                self.assertTrue(home.is_quiescent(committed.state))

    def test_data_outcome_is_typed_and_preserves_clean_authority(
        self,
    ) -> None:
        (
            rn,
            home,
            _rn_before,
            home_before,
            issued,
            accepted,
        ) = self.start_write_evict(ChiCopyBackDecision.REQUEST_DATA)
        response_packet = accepted.emissions[0]
        response = response_packet.message
        self.assertIsInstance(response, ChiCompDBIDRespMessage)
        self.assertEqual(self.DBID + 1, response.data_buffer_id)

        wrong_terminal = home.step(
            accepted.state,
            ChiHomeAcceptCompAck(
                ChiNetworkPacket.response(
                    ChiCompAckMessage(
                        response.data_buffer_id,
                        response=ChiRespCode.UC,
                    ),
                    source_id=self.RN,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_atomic_fault(
            wrong_terminal,
            accepted.state,
            "write_evict_terminal",
        )

        copied = self.apply(
            rn,
            issued.state,
            ChiRnAcceptCompDBIDResp(response_packet),
        )
        copyback_packet = copied.emissions[0]
        copyback = copyback_packet.message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertIs(ChiRespCode.UC, copyback.response)
        self.assertEqual(self.DATA, copyback.data)

        wrong_dbid_packet = replace(
            copyback_packet,
            message=replace(
                copyback,
                transaction_id=copyback.transaction_id + 1,
            ),
        )
        wrong_dbid = home.step(
            accepted.state,
            ChiHomeAcceptCopyBackData(wrong_dbid_packet),
        )
        self.assert_atomic_fault(
            wrong_dbid,
            accepted.state,
            "copyback_identity",
        )

        committed = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptCopyBackData(copyback_packet),
        )
        self.assertEqual(
            home_before.backing.line_at(self.ADDRESS),
            committed.state.backing.line_at(self.ADDRESS),
        )
        self.assert_retired_clean_victim(copied.state, committed.state)

        replay = home.step(
            committed.state,
            ChiHomeAcceptCopyBackData(copyback_packet),
        )
        self.assert_atomic_fault(
            replay,
            committed.state,
            "copyback_identity",
        )

    def test_no_data_outcome_uses_comp_ack_and_rejects_bad_terminals(
        self,
    ) -> None:
        (
            rn,
            home,
            _rn_before,
            home_before,
            issued,
            accepted,
        ) = self.start_write_evict(
            ChiCopyBackDecision.COMPLETE_WITHOUT_DATA
        )
        response_packet = accepted.emissions[0]
        response = response_packet.message
        self.assertIsInstance(response, ChiCompMessage)
        self.assertIs(ChiRespCode.I, response.response)
        self.assertEqual(self.DBID + 1, response.data_buffer_id)

        wrong_state_packet = replace(
            response_packet,
            message=replace(response, response=ChiRespCode.UC),
        )
        wrong_state = rn.step(
            issued.state,
            ChiRnAcceptComp(wrong_state_packet),
        )
        self.assert_atomic_fault(
            wrong_state,
            issued.state,
            "copyback_no_data_completion_state",
        )

        forged_data = ChiNetworkPacket.data(
            ChiCopyBackWrDataMessage(
                response.data_buffer_id,
                self.DATA,
                response=ChiRespCode.UC,
            ),
            source_id=self.RN,
            target_id=self.HOME,
        )
        wrong_terminal = home.step(
            accepted.state,
            ChiHomeAcceptCopyBackData(forged_data),
        )
        self.assert_atomic_fault(
            wrong_terminal,
            accepted.state,
            "write_evict_terminal",
        )

        acknowledged = self.apply(
            rn,
            issued.state,
            ChiRnAcceptComp(response_packet),
        )
        ack_packet = acknowledged.emissions[0]
        ack = ack_packet.message
        self.assertIsInstance(ack, ChiCompAckMessage)
        self.assertEqual(int(ChiRespCode.UC), ack.response)
        self.assertEqual(response.data_buffer_id, ack.transaction_id)

        wrong_dbid_packet = replace(
            ack_packet,
            message=replace(
                ack,
                transaction_id=ack.transaction_id + 1,
            ),
        )
        wrong_dbid = home.step(
            accepted.state,
            ChiHomeAcceptCompAck(wrong_dbid_packet),
        )
        self.assert_atomic_fault(
            wrong_dbid,
            accepted.state,
            "completion_ack_identity",
        )

        protected_copy = accepted.state.clean_residency
        committed = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptCompAck(ack_packet),
        )
        self.assertIs(protected_copy, committed.state.clean_residency)
        self.assertEqual(
            home_before.backing.line_at(self.ADDRESS),
            committed.state.backing.line_at(self.ADDRESS),
        )
        self.assert_retired_clean_victim(
            acknowledged.state,
            committed.state,
        )

        replay = home.step(
            committed.state,
            ChiHomeAcceptCompAck(ack_packet),
        )
        self.assert_atomic_fault(
            replay,
            committed.state,
            "completion_ack_identity",
        )


if __name__ == "__main__":
    unittest.main()
