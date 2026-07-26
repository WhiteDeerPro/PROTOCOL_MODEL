from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpCancel,
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
    ChiReadNoSnpObservePCrdGrant,
    ChiReadNoSnpObserveRetryAck,
    ChiReadNoSnpRetry,
    ChiReadNoSnpRetryEntry,
    ChiReadNoSnpRetryLedger,
    ChiReadNoSnpRetryPhase,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiDirectHomeAccept,
    ChiDirectHomeService,
    ChiRetryDebt,
    ChiRetryHomeGrant,
    ChiRetryHomeNode,
    ChiRetryHomeReturn,
    ChiRetryHomeState,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiPCrdReturnMessage,
    ChiPCrdGrantMessage,
    ChiReadNoSnpMessage,
    ChiRetryAckMessage,
)


class ChiIssueHRetryLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=2,
        )
        self.request = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0x4020,
            size=3,
            order=0,
            allow_retry=True,
            protocol_credit_type=0,
            expect_completion_ack=False,
            memory_attributes=0,
        )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_grant_before_retry_ack_is_pooled_then_consumed(self) -> None:
        ledger = ChiReadNoSnpRetryLedger("rn.retry", self.profile)
        state = self.apply(
            ledger, ledger.initial_state(), ChiReadNoSnpIssue(self.request)
        ).state
        grant = ChiPCrdGrantMessage(5)
        state = self.apply(
            ledger, state, ChiReadNoSnpObservePCrdGrant(grant)
        ).state
        ack = ChiRetryAckMessage(3, 5)
        state = self.apply(
            ledger, state, ChiReadNoSnpObserveRetryAck(ack)
        ).state

        retried = self.apply(
            ledger, state, ChiReadNoSnpRetry(self.request.transaction_id)
        )

        self.assertEqual(1, len(retried.emissions))
        request = retried.emissions[0]
        self.assertFalse(request.allow_retry)
        self.assertEqual(5, request.protocol_credit_type)
        self.assertEqual({}, retried.state.protocol_credits)
        self.assertIs(
            ChiReadNoSnpRetryPhase.RETRIED_IN_FLIGHT,
            retried.state.entries[self.request.transaction_id].phase,
        )

    def test_wrong_credit_type_cannot_authorize_retry(self) -> None:
        ledger = ChiReadNoSnpRetryLedger("rn.retry", self.profile)
        state = self.apply(
            ledger, ledger.initial_state(), ChiReadNoSnpIssue(self.request)
        ).state
        state = self.apply(
            ledger,
            state,
            ChiReadNoSnpObserveRetryAck(
                ChiRetryAckMessage(3, 4)
            ),
        ).state
        state = self.apply(
            ledger,
            state,
            ChiReadNoSnpObservePCrdGrant(
                ChiPCrdGrantMessage(5)
            ),
        ).state

        transition = ledger.step(
            state, ChiReadNoSnpRetry(self.request.transaction_id)
        )

        self.assertIsNotNone(transition.fault)
        self.assertIs(state, transition.state)

    def test_cancel_returns_matching_pcredit_and_retires_request(self) -> None:
        ledger = ChiReadNoSnpRetryLedger("rn.retry", self.profile)
        state = self.apply(
            ledger, ledger.initial_state(), ChiReadNoSnpIssue(self.request)
        ).state
        state = self.apply(
            ledger,
            state,
            ChiReadNoSnpObserveRetryAck(
                ChiRetryAckMessage(3, 6)
            ),
        ).state
        state = self.apply(
            ledger,
            state,
            ChiReadNoSnpObservePCrdGrant(
                ChiPCrdGrantMessage(6)
            ),
        ).state

        canceled = self.apply(
            ledger, state, ChiReadNoSnpCancel(self.request.transaction_id)
        )

        self.assertEqual(
            (ChiPCrdReturnMessage(6),), canceled.emissions
        )
        self.assertEqual({}, canceled.state.entries)
        self.assertEqual({}, canceled.state.protocol_credits)
        self.assertTrue(ledger.is_quiescent(canceled.state))

    def test_home_grant_reserves_acceptance_for_credited_request(self) -> None:
        home = ChiRetryHomeNode(
            "home",
            self.profile,
            lambda request: 0xD000_0000 | request.address,
            request_capacity=1,
            retry_policy=lambda request, state: 6,
        )
        state = home.initial_state()
        rejected = self.apply(
            home, state, ChiDirectHomeAccept(self.request)
        )
        self.assertIsInstance(rejected.emissions[0], ChiRetryAckMessage)

        granted = self.apply(
            home, rejected.state, ChiRetryHomeGrant()
        )
        self.assertIsInstance(granted.emissions[0], ChiPCrdGrantMessage)
        self.assertEqual(1, granted.state.reserved_count)

        credited = replace(
            self.request, allow_retry=False, protocol_credit_type=6
        )
        accepted = self.apply(
            home, granted.state, ChiDirectHomeAccept(credited)
        )
        self.assertEqual(0, accepted.state.reserved_count)
        self.assertEqual(1, accepted.state.depth)
        completed = self.apply(
            home, accepted.state, ChiDirectHomeService()
        )
        self.assertIsInstance(completed.emissions[0], ChiCompDataMessage)
        self.assertTrue(home.is_quiescent(completed.state))

    def test_home_rejects_credited_request_without_reservation(self) -> None:
        home = ChiRetryHomeNode(
            "home",
            self.profile,
            lambda request: 0,
            request_capacity=1,
        )
        credited = replace(
            self.request, allow_retry=False, protocol_credit_type=2
        )

        transition = home.step(
            home.initial_state(), ChiDirectHomeAccept(credited)
        )

        self.assertIsNotNone(transition.fault)

    def test_home_pcredit_return_releases_reserved_slot(self) -> None:
        home = ChiRetryHomeNode(
            "home",
            self.profile,
            lambda request: 0,
            request_capacity=1,
            retry_policy=lambda request, state: 6,
        )
        rejected = self.apply(
            home,
            home.initial_state(),
            ChiDirectHomeAccept(self.request),
        )
        granted = self.apply(home, rejected.state, ChiRetryHomeGrant())

        returned = self.apply(
            home,
            granted.state,
            ChiRetryHomeReturn(ChiPCrdReturnMessage(6)),
        )

        self.assertEqual(0, returned.state.reserved_count)
        self.assertEqual(1, returned.state.returned_credit_count)
        self.assertTrue(home.is_quiescent(returned.state))

    def test_retry_entry_rejects_mutated_or_uncredited_phase(self) -> None:
        with self.assertRaises(ValueError):
            ChiReadNoSnpRetryEntry(
                self.request,
                replace(self.request, address=self.request.address + 8),
                ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT,
                protocol_credit_type=3,
            )
        with self.assertRaises(ValueError):
            ChiReadNoSnpRetryEntry(
                self.request,
                self.request,
                ChiReadNoSnpRetryPhase.RETRIED_IN_FLIGHT,
                protocol_credit_type=3,
            )

    def test_home_state_rejects_broken_credit_conservation(self) -> None:
        debt = ChiRetryDebt(0x07, 3, 4)
        with self.assertRaises(ValueError):
            ChiRetryHomeState(retry_debts=(debt,))
        with self.assertRaises(ValueError):
            ChiRetryHomeState(
                reserved_by_requester_and_type={(0x07, 16): 1},
                retry_ack_count=1,
                grant_count=1,
            )


if __name__ == "__main__":
    unittest.main()
