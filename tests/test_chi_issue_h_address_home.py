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
    ChiRespErr,
)
from protocol_model.virtual_dut.address import (
    AddressSpace,
    MemoryRegion,
    RegisterPermission,
    RegisterRegion,
    RegisterSpec,
)


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

    def test_decode_error_completes_as_nderr_without_state_pollution(self) -> None:
        initial = self.home.initial_state()
        request = self.request(
            address=self.BASE + self.profile.data_bytes
        )
        accepted = self.home.step(
            initial,
            ChiDirectHomeAccept(request),
        )
        self.assertIsNone(accepted.fault)

        completed = self.home.step(
            accepted.state, ChiDirectHomeService()
        )
        self.assertIsNone(completed.fault)
        self.assertIsNone(completed.blocked)
        self.assertEqual(1, len(completed.emissions))
        response = completed.emissions[0]
        self.assertIs(ChiRespErr.NDERR, response.response_error)
        self.assertEqual(0, response.response)
        self.assertEqual(0, response.data)
        self.assertEqual(
            self.profile.expected_data_id(request.address),
            response.data_id,
        )
        self.assertFalse(completed.state.pending)
        self.assertIs(
            initial.target_state,
            completed.state.target_state,
        )
        self.assertEqual(1, completed.state.completed_count)
        self.assertTrue(self.home.is_quiescent(completed.state))

    def test_access_error_completes_as_nderr_without_valid_data(self) -> None:
        target = AddressSpace(
            (
                RegisterRegion(
                    "write_only_registers",
                    (
                        RegisterSpec(
                            "command",
                            0,
                            width=self.profile.data_width,
                            permission=RegisterPermission.WRITE_ONLY,
                        ),
                    ),
                    base_address=self.BASE,
                ),
            )
        )
        home = ChiAddressHomeNode(
            "write_only_home",
            self.profile,
            target,
            request_capacity=1,
        )
        initial = home.initial_state()
        accepted = home.step(
            initial,
            ChiDirectHomeAccept(self.request()),
        )

        completed = home.step(
            accepted.state,
            ChiDirectHomeService(),
        )

        self.assertIsNone(completed.fault)
        response = completed.emissions[0]
        self.assertIs(ChiRespErr.NDERR, response.response_error)
        self.assertEqual(0, response.data)
        self.assertEqual(initial.target_state, completed.state.target_state)
        self.assertTrue(home.is_quiescent(completed.state))


if __name__ == "__main__":
    unittest.main()
