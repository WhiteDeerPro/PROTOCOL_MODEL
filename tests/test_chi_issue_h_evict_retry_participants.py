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
    ChiHomeAcceptEvict,
    ChiHomeDirectoryEntry,
    ChiHomeGrantPCredit,
    ChiRnAcceptComp,
    ChiRnAcceptPCrdGrant,
    ChiRnAcceptRetryAck,
    ChiRnIssueEvict,
    ChiRnRetryCoherentRequest,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompMessage,
    ChiEvictMessage,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiRetryAckMessage,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)


class ChiIssueHEvictRetryParticipantTest(unittest.TestCase):
    REQUESTER = 0x07
    OTHER_REQUESTER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    OTHER_ADDRESS = 0x8040
    DATA = (1 << 400) | 0xE71C7
    OTHER_DATA = (1 << 401) | 0xE71C8
    TRANSACTION_ID = 0x12
    CREDIT_TYPE = 5
    SNOOP_ID = 0x100
    DATA_BUFFER_ID = 0x200

    def build_requester(self):
        return build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
            ),
        )

    def build_home(
        self,
        *,
        evict_retry_policy=None,
        retry_policy=None,
        transaction_capacity: int = 1,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.DATA),
                    BackingLine(self.OTHER_ADDRESS, self.OTHER_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.REQUESTER,
                ),
                ChiHomeDirectoryEntry(self.OTHER_ADDRESS),
            ),
            transaction_capacity=transaction_capacity,
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DATA_BUFFER_ID,
            default_protocol_credit_type=self.CREDIT_TYPE,
            retry_policy=retry_policy,
            evict_retry_policy=evict_retry_policy,
        )

    def request(self) -> ChiEvictMessage:
        return ChiEvictMessage(
            transaction_id=self.TRANSACTION_ID,
            address=self.ADDRESS,
        )

    def request_packet(
        self,
        request: ChiEvictMessage | None = None,
        *,
        source_id: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            self.request() if request is None else request,
            source_id=(
                self.REQUESTER if source_id is None else source_id
            ),
            target_id=self.HOME,
        )

    def retry_ack_packet(
        self,
        *,
        transaction_id: int | None = None,
        credit_type: int | None = None,
        source_id: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiRetryAckMessage(
                transaction_id=(
                    self.TRANSACTION_ID
                    if transaction_id is None
                    else transaction_id
                ),
                protocol_credit_type=(
                    self.CREDIT_TYPE
                    if credit_type is None
                    else credit_type
                ),
            ),
            source_id=self.HOME if source_id is None else source_id,
            target_id=self.REQUESTER,
        )

    def pcredit_packet(
        self,
        credit_type: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiPCrdGrantMessage(
                self.CREDIT_TYPE
                if credit_type is None
                else credit_type
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def completion_packet(
        self,
        *,
        transaction_id: int | None = None,
    ) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiCompMessage(
                transaction_id=(
                    self.TRANSACTION_ID
                    if transaction_id is None
                    else transaction_id
                ),
                data_buffer_id=0,
                response=ChiRespCode.I,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_fault_preserves_state(
        self,
        component,
        state,
        action,
    ) -> None:
        transition = component.step(state, action)
        self.assertIsNotNone(transition.fault)
        self.assertIsNone(transition.blocked)
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

    def test_requester_reissues_canonical_evict_and_comp_i_retires(
        self,
    ) -> None:
        requester = self.build_requester()
        original = self.request()
        issued = self.apply(
            requester,
            requester.initial_state(),
            ChiRnIssueEvict(original),
        )

        line = issued.state.line_at(self.ADDRESS)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        entry = issued.state.request_retry.entries[self.TRANSACTION_ID]
        self.assertEqual(original, entry.original_request)
        self.assertEqual(original, entry.current_request)
        self.assertIs(
            ChiRequestRetryPhase.INITIAL_IN_FLIGHT,
            entry.phase,
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
        self.assert_fault_preserves_state(
            requester,
            acknowledged.state,
            ChiRnAcceptComp(self.completion_packet()),
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
        self.assertEqual((expected,), tuple(
            packet.message for packet in retried.emissions
        ))
        self.assertEqual(
            expected,
            retried.state.pending_transactions[self.TRANSACTION_ID],
        )
        entry = retried.state.request_retry.entries[
            self.TRANSACTION_ID
        ]
        self.assertEqual(original, entry.original_request)
        self.assertEqual(expected, entry.current_request)
        self.assertIs(
            ChiRequestRetryPhase.RETRIED_IN_FLIGHT,
            entry.phase,
        )
        self.assert_fault_preserves_state(
            requester,
            retried.state,
            ChiRnRetryCoherentRequest(self.TRANSACTION_ID),
        )

        completed = self.apply(
            requester,
            retried.state,
            ChiRnAcceptComp(self.completion_packet()),
        )
        self.assertFalse(completed.state.pending_transactions)
        self.assertFalse(completed.state.request_retry.entries)
        self.assertTrue(requester.is_quiescent(completed.state))
        self.assert_fault_preserves_state(
            requester,
            completed.state,
            ChiRnAcceptComp(self.completion_packet()),
        )

    def test_requester_wrong_identity_and_credit_fail_atomically(
        self,
    ) -> None:
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
            ChiRnIssueEvict(self.request()),
        )
        self.assert_fault_preserves_state(
            requester,
            issued.state,
            ChiRnAcceptRetryAck(
                self.retry_ack_packet(source_id=self.HOME + 1)
            ),
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
        matching_credit = self.apply(
            requester,
            wrong_credit.state,
            ChiRnAcceptPCrdGrant(self.pcredit_packet()),
        )
        retried = self.apply(
            requester,
            matching_credit.state,
            ChiRnRetryCoherentRequest(self.TRANSACTION_ID),
        )
        self.assert_fault_preserves_state(
            requester,
            retried.state,
            ChiRnAcceptComp(
                self.completion_packet(
                    transaction_id=self.TRANSACTION_ID + 1
                )
            ),
        )

    def test_home_retry_rejection_and_credited_accept_are_atomic(
        self,
    ) -> None:
        home = self.build_home(
            evict_retry_policy=(
                lambda _request, _state: self.CREDIT_TYPE
            ),
        )
        initial = home.initial_state()
        credited_request = replace(
            self.request(),
            allow_retry=False,
            protocol_credit_type=self.CREDIT_TYPE,
        )
        self.assert_fault_preserves_state(
            home,
            initial,
            ChiHomeAcceptEvict(
                self.request_packet(credited_request)
            ),
        )

        rejected = self.apply(
            home,
            initial,
            ChiHomeAcceptEvict(self.request_packet()),
        )
        self.assertEqual(1, len(rejected.emissions))
        retry_ack = rejected.emissions[0]
        self.assertEqual(
            ChiRetryAckMessage(
                self.TRANSACTION_ID,
                self.CREDIT_TYPE,
            ),
            retry_ack.message,
        )
        self.assertEqual(initial.directory, rejected.state.directory)
        self.assertIs(initial.backing, rejected.state.backing)
        self.assertEqual(initial.pending, rejected.state.pending)
        self.assertEqual(
            initial.pending_writebacks,
            rejected.state.pending_writebacks,
        )
        self.assertEqual(
            initial.next_snoop_transaction_id,
            rejected.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            initial.next_data_buffer_id,
            rejected.state.next_data_buffer_id,
        )
        self.assertEqual(
            1,
            len(rejected.state.request_retry.retry_debts),
        )
        self.assertEqual(
            0,
            rejected.state.request_retry.reserved_count,
        )
        self.assert_fault_preserves_state(
            home,
            rejected.state,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        granted = self.apply(
            home,
            rejected.state,
            ChiHomeGrantPCredit(),
        )
        self.assertIsInstance(
            granted.emissions[0].message,
            ChiPCrdGrantMessage,
        )
        self.assertEqual(
            1,
            granted.state.request_retry.reserved_count,
        )
        self.assert_fault_preserves_state(
            home,
            granted.state,
            ChiHomeAcceptEvict(
                self.request_packet(
                    credited_request,
                    source_id=self.OTHER_REQUESTER,
                )
            ),
        )
        wrong_credit = replace(
            credited_request,
            protocol_credit_type=self.CREDIT_TYPE + 1,
        )
        self.assert_fault_preserves_state(
            home,
            granted.state,
            ChiHomeAcceptEvict(
                self.request_packet(wrong_credit)
            ),
        )

        accepted = self.apply(
            home,
            granted.state,
            ChiHomeAcceptEvict(
                self.request_packet(credited_request)
            ),
        )
        self.assertEqual(1, len(accepted.emissions))
        self.assertEqual(
            ChiCompMessage(
                self.TRANSACTION_ID,
                data_buffer_id=0,
                response=ChiRespCode.I,
            ),
            accepted.emissions[0].message,
        )
        self.assertIsNone(
            accepted.state.directory[self.ADDRESS].unique_owner
        )
        self.assertIs(granted.state.backing, accepted.state.backing)
        self.assertEqual(
            granted.state.next_snoop_transaction_id,
            accepted.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            granted.state.next_data_buffer_id,
            accepted.state.next_data_buffer_id,
        )
        retry = accepted.state.request_retry
        self.assertEqual(1, retry.retry_ack_count)
        self.assertEqual(1, retry.grant_count)
        self.assertEqual(1, retry.consumed_count)
        self.assertEqual(0, retry.reserved_count)
        self.assert_fault_preserves_state(
            home,
            accepted.state,
            ChiHomeAcceptEvict(
                self.request_packet(credited_request)
            ),
        )

    def test_read_unique_retry_policy_does_not_enable_evict_retry(
        self,
    ) -> None:
        home = self.build_home(
            retry_policy=(
                lambda _request, _state: self.CREDIT_TYPE
            ),
        )

        accepted = self.apply(
            home,
            home.initial_state(),
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assertIsInstance(
            accepted.emissions[0].message,
            ChiCompMessage,
        )
        self.assertFalse(
            accepted.state.request_retry.retry_debts
        )
        self.assertIsNone(
            accepted.state.directory[self.ADDRESS].unique_owner
        )

    def test_full_table_uses_evict_policy_default_credit_type(
        self,
    ) -> None:
        home = self.build_home(
            evict_retry_policy=lambda _request, _state: None,
            transaction_capacity=1,
        )
        initial = home.initial_state()
        active_request = ChiReadUniqueMessage(
            transaction_id=self.TRANSACTION_ID + 1,
            address=self.OTHER_ADDRESS,
        )
        active = self.apply(
            home,
            initial,
            ChiHomeAcceptCoherentRead(
                ChiNetworkPacket.request(
                    active_request,
                    source_id=self.OTHER_REQUESTER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assertEqual(1, len(active.state.pending))

        rejected = self.apply(
            home,
            active.state,
            ChiHomeAcceptEvict(self.request_packet()),
        )

        self.assertEqual(
            ChiRetryAckMessage(
                self.TRANSACTION_ID,
                self.CREDIT_TYPE,
            ),
            rejected.emissions[0].message,
        )
        self.assertEqual(active.state.pending, rejected.state.pending)
        self.assertEqual(active.state.directory, rejected.state.directory)
        self.assertIs(active.state.backing, rejected.state.backing)
        self.assertEqual(
            active.state.next_snoop_transaction_id,
            rejected.state.next_snoop_transaction_id,
        )
        self.assertEqual(
            active.state.next_data_buffer_id,
            rejected.state.next_data_buffer_id,
        )

    def test_home_rejects_evict_identity_owned_by_an_active_request(
        self,
    ) -> None:
        home = self.build_home(
            evict_retry_policy=(
                lambda _request, _state: self.CREDIT_TYPE
            ),
            transaction_capacity=2,
        )
        initial = home.initial_state()
        active_request = ChiReadUniqueMessage(
            transaction_id=self.TRANSACTION_ID,
            address=self.OTHER_ADDRESS,
        )
        active = self.apply(
            home,
            initial,
            ChiHomeAcceptCoherentRead(
                ChiNetworkPacket.request(
                    active_request,
                    source_id=self.REQUESTER,
                    target_id=self.HOME,
                )
            ),
        )

        self.assert_fault_preserves_state(
            home,
            active.state,
            ChiHomeAcceptEvict(self.request_packet()),
        )

    def test_invalid_evict_retry_policy_result_is_atomic(self) -> None:
        for credit_type in (True, 16):
            with self.subTest(credit_type=credit_type):
                home = self.build_home(
                    evict_retry_policy=(
                        lambda _request, _state: credit_type
                    ),
                )
                initial = home.initial_state()

                self.assert_fault_preserves_state(
                    home,
                    initial,
                    ChiHomeAcceptEvict(self.request_packet()),
                )


if __name__ == "__main__":
    unittest.main()
