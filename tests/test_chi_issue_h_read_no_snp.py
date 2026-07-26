from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiReadNoSnpMessage,
)


class ChiIssueHReadNoSnpLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=1,
        )
        self.ledger = ChiReadNoSnpDirectLedger("rn_i.reads", self.profile)
        self.home = ChiDirectHomeNode(
            "home",
            self.profile,
            lambda request: 0xA500_0000 | request.transaction_id,
            request_capacity=1,
        )

    @staticmethod
    def read(transaction_id: int, *, address: int = 0x4000):
        return ChiReadNoSnpMessage(
            transaction_id=transaction_id,
            address=address,
            size=3,
            order=0,
            allow_retry=True,
            protocol_credit_type=0,
            expect_completion_ack=False,
            memory_attributes=0,
        )

    def test_direct_home_comp_data_closes_the_read_lifecycle(self) -> None:
        request = self.read(3)
        ledger_state = self.ledger.initial_state()
        issued = self.ledger.step(ledger_state, ChiReadNoSnpIssue(request))
        self.assertIsNone(issued.fault)
        self.assertFalse(self.ledger.is_quiescent(issued.state))

        home_state = self.home.initial_state()
        accepted = self.home.step(home_state, ChiDirectHomeAccept(request))
        self.assertIsNone(accepted.fault)
        serviced = self.home.step(accepted.state, ChiDirectHomeService())
        self.assertIsNone(serviced.fault)
        response = serviced.emissions[0]
        self.assertEqual(3, response.semantic_key)
        self.assertEqual(0x21, response.home_node_id)

        completed = self.ledger.step(
            issued.state, ChiReadNoSnpComplete(response)
        )
        self.assertIsNone(completed.fault)
        self.assertEqual(0xA500_0003, completed.emissions[0].data)
        self.assertTrue(self.ledger.is_quiescent(completed.state))

    def test_outstanding_capacity_blocks_without_accepting_second_read(self) -> None:
        state = self.ledger.initial_state()
        state = self.ledger.step(
            state, ChiReadNoSnpIssue(self.read(1))
        ).state

        blocked = self.ledger.step(
            state, ChiReadNoSnpIssue(self.read(2))
        )

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)

    def test_unknown_or_wrong_comp_data_does_not_release_request(self) -> None:
        request = self.read(3)
        state = self.ledger.step(
            self.ledger.initial_state(), ChiReadNoSnpIssue(request)
        ).state
        unknown = ChiCompDataMessage(
            transaction_id=4,
            home_node_id=0x21,
            data=0,
        )
        failed = self.ledger.step(state, ChiReadNoSnpComplete(unknown))
        self.assertIsNotNone(failed.fault)
        self.assertIs(state, failed.state)

        wrong_home = ChiCompDataMessage(
            transaction_id=3,
            home_node_id=0x20,
            data=0,
        )
        failed = self.ledger.step(state, ChiReadNoSnpComplete(wrong_home))
        self.assertIsNotNone(failed.fault)
        self.assertIs(state, failed.state)
        self.assertIn(3, failed.state.outstanding)

    def test_request_crossing_one_dat_chunk_is_outside_subset(self) -> None:
        request = self.read(3, address=0x400C)
        failed = self.ledger.step(
            self.ledger.initial_state(), ChiReadNoSnpIssue(request)
        )
        self.assertIsNotNone(failed.fault)
        self.assertIn("crosses", failed.fault.reason)


if __name__ == "__main__":
    unittest.main()
