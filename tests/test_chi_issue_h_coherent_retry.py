from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiRequestRetryPhase,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptCoherentRead,
    ChiHomeAcceptWriteBackFull,
    ChiHomeDirectoryEntry,
    ChiHomeGrantPCredit,
    ChiRnAcceptCompData,
    ChiRnAcceptPCrdGrant,
    ChiRnAcceptRetryAck,
    ChiRnIssueCoherentRead,
    ChiRnRetryCoherentRequest,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiRetryAckMessage,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiGrantCoherentHomePCredit,
    ChiRetryCoherentRequest,
    ChiSubmitCoherentRead,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHCoherentRetryParticipantTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC0DE
    TRANSACTION_ID = 0x12
    CREDIT_TYPE = 5
    SNOOP_ID = 0x100
    DATA_BUFFER_ID = 0x200

    def build_requester(self):
        return build_chi_cache_participant_fixture(
            "rn0",
            self.REQUESTER,
            self.HOME,
        )

    def build_peer(self):
        return build_chi_cache_participant_fixture(
            "rn1",
            self.PEER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    self.DATA,
                ),
            ),
        )

    def build_home(self, *, enable_retry: bool = True):
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=frozenset((self.PEER,)),
                ),
            ),
            transaction_capacity=1,
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DATA_BUFFER_ID,
            retry_policy=(
                (lambda _request, _state: self.CREDIT_TYPE)
                if enable_retry
                else None
            ),
        )

    def request(self) -> ChiReadUniqueMessage:
        return ChiReadUniqueMessage(
            transaction_id=self.TRANSACTION_ID,
            address=self.ADDRESS,
        )

    def request_packet(
        self,
        request: ChiReadUniqueMessage | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            self.request() if request is None else request,
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )

    def retry_ack_packet(
        self,
        *,
        transaction_id: int | None = None,
        credit_type: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiRetryAckMessage(
                (
                    self.TRANSACTION_ID
                    if transaction_id is None
                    else transaction_id
                ),
                self.CREDIT_TYPE if credit_type is None else credit_type,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def pcredit_packet(
        self,
        credit_type: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiPCrdGrantMessage(
                self.CREDIT_TYPE if credit_type is None else credit_type
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def completion_packet(self) -> ChiNetworkPacket:
        return ChiNetworkPacket.data(
            ChiCompDataMessage(
                transaction_id=self.TRANSACTION_ID,
                data=self.DATA,
                home_node_id=self.HOME,
                response=ChiRespCode.UC,
                data_buffer_id=self.DATA_BUFFER_ID,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_fault_preserves_state(self, component, state, action) -> None:
        transition = component.step(state, action)
        self.assertIsNotNone(transition.fault)
        self.assertIsNone(transition.blocked)
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

    def test_forced_retry_changes_only_the_home_retry_ledger(self) -> None:
        home = self.build_home()
        state = home.initial_state()

        rejected = self.apply(
            home,
            state,
            ChiHomeAcceptCoherentRead(self.request_packet()),
        )

        self.assertEqual(1, len(rejected.emissions))
        self.assertIsInstance(
            rejected.emissions[0].message,
            ChiRetryAckMessage,
        )
        self.assertEqual(state.pending, rejected.state.pending)
        self.assertEqual(state.directory, rejected.state.directory)
        self.assertIs(state.backing, rejected.state.backing)
        self.assertEqual(
            state.next_snoop_transaction_id,
            rejected.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            state.next_data_buffer_id,
            rejected.state.next_data_buffer_id,
        )
        self.assertEqual(
            1,
            len(rejected.state.request_retry.retry_debts),
        )
        self.assertEqual(0, rejected.state.request_retry.reserved_count)

    def test_credited_home_request_requires_matching_reservation(self) -> None:
        home = self.build_home()
        initial = home.initial_state()
        credited = replace(
            self.request(),
            allow_retry=False,
            protocol_credit_type=self.CREDIT_TYPE,
        )

        self.assert_fault_preserves_state(
            home,
            initial,
            ChiHomeAcceptCoherentRead(self.request_packet(credited)),
        )

        rejected = self.apply(
            home,
            initial,
            ChiHomeAcceptCoherentRead(self.request_packet()),
        )
        granted = self.apply(
            home,
            rejected.state,
            ChiHomeGrantPCredit(),
        )
        wrong_type = replace(
            credited,
            protocol_credit_type=self.CREDIT_TYPE + 1,
        )
        self.assert_fault_preserves_state(
            home,
            granted.state,
            ChiHomeAcceptCoherentRead(
                self.request_packet(wrong_type)
            ),
        )

    def test_requester_retry_failures_preserve_the_whole_state(self) -> None:
        requester = self.build_requester()
        initial = requester.initial_state()
        self.assert_fault_preserves_state(
            requester,
            initial,
            ChiRnAcceptRetryAck(
                self.retry_ack_packet(
                    transaction_id=self.TRANSACTION_ID + 1
                )
            ),
        )

        issued = self.apply(
            requester,
            initial,
            ChiRnIssueCoherentRead(self.request()),
        )
        acknowledged = self.apply(
            requester,
            issued.state,
            ChiRnAcceptRetryAck(self.retry_ack_packet()),
        )
        self.assert_fault_preserves_state(
            requester,
            acknowledged.state,
            ChiRnAcceptRetryAck(self.retry_ack_packet()),
        )

        wrong_credit = self.apply(
            requester,
            acknowledged.state,
            ChiRnAcceptPCrdGrant(
                self.pcredit_packet(self.CREDIT_TYPE + 1)
            ),
        )
        self.assert_fault_preserves_state(
            requester,
            wrong_credit.state,
            ChiRnRetryCoherentRequest(self.TRANSACTION_ID),
        )
        self.assert_fault_preserves_state(
            requester,
            wrong_credit.state,
            ChiRnAcceptCompData(self.completion_packet()),
        )

    def test_grant_before_ack_authorizes_only_the_canonical_reissue(
        self,
    ) -> None:
        requester = self.build_requester()
        original = self.request()
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueCoherentRead(original),
        )
        credited = self.apply(
            requester,
            issued.state,
            ChiRnAcceptPCrdGrant(self.pcredit_packet()),
        )
        acknowledged = self.apply(
            requester,
            credited.state,
            ChiRnAcceptRetryAck(self.retry_ack_packet()),
        )

        retried = self.apply(
            requester,
            acknowledged.state,
            ChiRnRetryCoherentRequest(self.TRANSACTION_ID),
        )

        expected = replace(
            original,
            allow_retry=False,
            protocol_credit_type=self.CREDIT_TYPE,
        )
        self.assertEqual(1, len(retried.emissions))
        self.assertEqual(expected, retried.emissions[0].message)
        entry = retried.state.request_retry.entries[
            self.TRANSACTION_ID
        ]
        self.assertEqual(original, entry.original_request)
        self.assertEqual(expected, entry.current_request)
        self.assertIs(
            ChiRequestRetryPhase.RETRIED_IN_FLIGHT,
            entry.phase,
        )
        self.assertEqual(
            expected,
            retried.state.pending_transactions[self.TRANSACTION_ID],
        )
        self.assertEqual({}, retried.state.request_retry.protocol_credits)

    def test_home_grant_and_credited_accept_conserve_capacity(self) -> None:
        home = self.build_home()
        initial = home.initial_state()
        rejected = self.apply(
            home,
            initial,
            ChiHomeAcceptCoherentRead(self.request_packet()),
        )
        granted = self.apply(
            home,
            rejected.state,
            ChiHomeGrantPCredit(),
        )

        retry = granted.state.request_retry
        self.assertEqual(1, retry.retry_ack_count)
        self.assertEqual(1, retry.grant_count)
        self.assertEqual(0, retry.consumed_count)
        self.assertEqual(1, retry.reserved_count)
        self.assertFalse(retry.retry_debts)

        credited = replace(
            self.request(),
            allow_retry=False,
            protocol_credit_type=self.CREDIT_TYPE,
        )
        accepted = self.apply(
            home,
            granted.state,
            ChiHomeAcceptCoherentRead(self.request_packet(credited)),
        )

        retry = accepted.state.request_retry
        self.assertEqual(
            retry.retry_ack_count,
            retry.grant_count + len(retry.retry_debts),
        )
        self.assertEqual(
            retry.grant_count,
            (
                retry.consumed_count
                + retry.returned_count
                + retry.reserved_count
            ),
        )
        self.assertEqual(1, retry.consumed_count)
        self.assertEqual(0, retry.reserved_count)
        self.assertEqual(1, len(accepted.state.pending))
        self.assertEqual(
            (self.SNOOP_ID + 1) % (1 << 12),
            accepted.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            (self.DATA_BUFFER_ID + 1) % (1 << 12),
            accepted.state.next_data_buffer_id,
        )

    def test_home_retry_reservation_blocks_writeback_admission(self) -> None:
        writeback_address = self.ADDRESS + 0x40
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.DATA),
                    BackingLine(writeback_address, self.DATA ^ 1),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=frozenset((self.PEER,)),
                ),
                ChiHomeDirectoryEntry(
                    writeback_address,
                    unique_owner=self.REQUESTER,
                ),
            ),
            transaction_capacity=1,
            allow_dirty_data_transfer=True,
            retry_policy=lambda _request, _state: self.CREDIT_TYPE,
        )
        rejected = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptCoherentRead(self.request_packet()),
        )
        granted = self.apply(
            home,
            rejected.state,
            ChiHomeGrantPCredit(),
        )
        writeback = ChiNetworkPacket.request(
            ChiWriteBackFullMessage(
                self.TRANSACTION_ID + 1,
                writeback_address,
            ),
            source_id=self.REQUESTER,
            target_id=self.HOME,
        )

        transition = home.step(
            granted.state,
            ChiHomeAcceptWriteBackFull(writeback),
        )

        self.assertIsNone(transition.fault)
        self.assertIsNotNone(transition.blocked)
        self.assertIs(granted.state, transition.state)
        self.assertFalse(transition.emissions)
        self.assertFalse(transition.state.pending_writebacks)
        self.assertEqual(1, transition.state.request_retry.reserved_count)

    def test_session_requires_retry_policy_for_enabled_feature(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires a configured coherent Home retry policy",
        ):
            ChiCoherenceSession(
                "coherent_retry",
                self.build_home(enable_retry=False),
                {
                    self.REQUESTER: self.build_requester(),
                    self.PEER: self.build_peer(),
                },
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                        CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
                    )
                ),
                requester_node_ids=frozenset((self.REQUESTER,)),
                snoopee_node_ids=frozenset((self.PEER,)),
            )

    def test_packet_delivery_session_closes_retry_and_coherence(
        self,
    ) -> None:
        session = ChiCoherenceSession(
            "coherent_retry",
            self.build_home(),
            {
                self.REQUESTER: self.build_requester(),
                self.PEER: self.build_peer(),
            },
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
                )
            ),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset((self.PEER,)),
        )
        state = session.initial_state()

        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                self.request(),
            ),
        )
        rejected = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        granted = self.apply(
            session,
            rejected.state,
            ChiGrantCoherentHomePCredit(),
        )
        credit_seen = self.apply(
            session,
            granted.state,
            ChiDeliverCoherencePacket(granted.emissions[0]),
        )
        ack_seen = self.apply(
            session,
            credit_seen.state,
            ChiDeliverCoherencePacket(rejected.emissions[0]),
        )
        retried = self.apply(
            session,
            ack_seen.state,
            ChiRetryCoherentRequest(
                self.REQUESTER,
                self.TRANSACTION_ID,
            ),
        )
        accepted = self.apply(
            session,
            retried.state,
            ChiDeliverCoherencePacket(retried.emissions[0]),
        )
        snooped = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(accepted.emissions[0]),
        )
        completed = self.apply(
            session,
            snooped.state,
            ChiDeliverCoherencePacket(snooped.emissions[0]),
        )
        installed = self.apply(
            session,
            completed.state,
            ChiDeliverCoherencePacket(completed.emissions[0]),
        )
        retired = self.apply(
            session,
            installed.state,
            ChiDeliverCoherencePacket(installed.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        requester = retired.state.request_nodes[self.REQUESTER]
        peer = retired.state.request_nodes[self.PEER]
        self.assertIs(
            ChiCacheState.UC,
            requester.lines[self.ADDRESS].state,
        )
        self.assertIs(ChiCacheState.I, peer.lines[self.ADDRESS].state)
        self.assertEqual(
            self.REQUESTER,
            retired.state.home.directory[self.ADDRESS].unique_owner,
        )
        self.assertEqual(
            self.DATA,
            retired.state.home.backing.line_at(self.ADDRESS).data,
        )


if __name__ == "__main__":
    unittest.main()
