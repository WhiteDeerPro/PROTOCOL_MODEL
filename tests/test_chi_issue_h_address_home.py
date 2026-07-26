from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectProfile,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiAddressHomeNode,
    ChiAddressHomeState,
    ChiDirectHomeAccept,
    ChiDirectHomeService,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiReadNoSnpMessage,
)
from protocol_model.virtual_dut.address import AddressSpace, MemoryRegion


class ChiIssueHAddressHomeTest(unittest.TestCase):
    BASE = 0x4020
    VALUE = 0x5300_4020

    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=2,
        )
        self.target = AddressSpace(
            (
                MemoryRegion(
                    "sensor_register",
                    self.profile.data_bytes,
                    base_address=self.BASE,
                    read_only=True,
                    initial_content=self.VALUE.to_bytes(
                        self.profile.data_bytes, "little"
                    ),
                ),
            )
        )
        self.home = ChiAddressHomeNode(
            "sensor_home",
            self.profile,
            self.target,
            request_capacity=1,
        )

    def request(self, **updates) -> ChiReadNoSnpMessage:
        values = {
            "transaction_id": 3,
            "address": self.BASE,
            "size": 4,
            "order": 0,
            "allow_retry": True,
            "protocol_credit_type": 0,
            "expect_completion_ack": False,
            "memory_attributes": 0,
        }
        values.update(updates)
        return ChiReadNoSnpMessage(**values)

    def test_reads_real_address_target_state_and_emits_comp_data(self) -> None:
        initial = self.home.initial_state()
        self.assertIsInstance(initial, ChiAddressHomeState)

        accepted = self.home.step(
            initial, ChiDirectHomeAccept(self.request())
        )
        self.assertIsNone(accepted.fault)
        self.assertIsNone(accepted.blocked)
        self.assertIs(initial.target_state, accepted.state.target_state)
        self.assertEqual(1, accepted.state.accepted_count)

        serviced = self.home.step(
            accepted.state, ChiDirectHomeService()
        )
        self.assertIsNone(serviced.fault)
        self.assertIsNone(serviced.blocked)
        response = serviced.emissions[0]
        self.assertEqual(self.VALUE, response.data)
        self.assertEqual(3, response.semantic_key)
        self.assertEqual(2, response.data_id)
        self.assertEqual(1, serviced.state.completed_count)
        self.assertTrue(self.home.is_quiescent(serviced.state))

    def test_unmodeled_sideband_is_rejected_without_accepting_request(self) -> None:
        initial = self.home.initial_state()
        failed = self.home.step(
            initial,
            ChiDirectHomeAccept(self.request(memory_attributes=0b0001)),
        )

        self.assertIsNotNone(failed.fault)
        self.assertIn("MemAttr", failed.fault.reason)
        self.assertIs(initial, failed.state)
        self.assertEqual(0, failed.state.accepted_count)

    def test_narrow_read_is_outside_first_address_home_profile(self) -> None:
        initial = self.home.initial_state()
        failed = self.home.step(
            initial, ChiDirectHomeAccept(self.request(size=3))
        )

        self.assertIsNotNone(failed.fault)
        self.assertIn("full-DAT-width", failed.fault.reason)
        self.assertIs(initial, failed.state)

    def test_decode_error_waits_for_a_future_chi_error_mapping(self) -> None:
        initial = self.home.initial_state()
        accepted = self.home.step(
            initial,
            ChiDirectHomeAccept(
                self.request(address=self.BASE + self.profile.data_bytes)
            ),
        )
        self.assertIsNone(accepted.fault)

        failed = self.home.step(
            accepted.state, ChiDirectHomeService()
        )
        self.assertIsNotNone(failed.fault)
        self.assertIn("RespErr/Resp", failed.fault.reason)
        self.assertIs(accepted.state, failed.state)
        self.assertEqual(1, len(failed.state.pending))


if __name__ == "__main__":
    unittest.main()
