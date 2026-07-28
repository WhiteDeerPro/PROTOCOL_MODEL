from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDBIDRespMessage,
    ChiCopyBackWrDataMessage,
    ChiDatOpcode,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiReqOpcode,
    ChiRespCode,
    ChiRspOpcode,
    ChiWriteBackFullMessage,
)


class ChiIssueHWriteBackRepresentationTest(unittest.TestCase):
    def test_writeback_full_is_a_routable_req_message(self) -> None:
        message = ChiWriteBackFullMessage(
            transaction_id=0x12,
            address=0x8000,
        )
        packet = ChiNetworkPacket.request(
            message,
            source_id=0x07,
            target_id=0x21,
        )

        self.assertEqual(ChiReqOpcode.WRITE_BACK_FULL, message.opcode)
        self.assertEqual(6, message.size)
        self.assertTrue(message.allow_retry)
        self.assertEqual(0, message.protocol_credit_type)
        self.assertFalse(message.expect_completion_ack)
        self.assertFalse(message.copy_at_home)
        self.assertTrue(ChiIssueHReqProfile().contains(message))
        self.assertFalse(packet.explain_profile())

    def test_writeback_full_profile_checks_its_fixed_shape(self) -> None:
        message = ChiWriteBackFullMessage(
            transaction_id=1,
            address=0x8000,
            size=5,
            allow_retry=True,
            protocol_credit_type=2,
            order=1,
            memory_attributes=0,
            snoop_attribute=False,
            exclusive=True,
            expect_completion_ack=True,
            copy_at_home=True,
        )

        explanation = "; ".join(ChiIssueHReqProfile().explain(message))
        for expected in (
            "Size=6",
            "SnpAttr=1",
            "MemAttr",
            "Order=0",
            "Excl=0",
            "ExpCompAck=0",
            "CAH=0",
            "PCrdType",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, explanation)

    def test_comp_dbid_response_keeps_request_txnid_and_new_dbid(self) -> None:
        message = ChiCompDBIDRespMessage(
            transaction_id=0x12,
            data_buffer_id=0x234,
        )
        packet = ChiNetworkPacket.response(
            message,
            source_id=0x21,
            target_id=0x07,
        )

        self.assertEqual(ChiRspOpcode.COMP_DBID_RESP, message.opcode)
        self.assertEqual(0x12, message.semantic_key)
        self.assertEqual(0x234, message.data_buffer_id)
        self.assertTrue(ChiIssueHRspProfile().contains(message))
        self.assertFalse(packet.explain_profile())

        invalid = ChiCompDBIDRespMessage(
            transaction_id=0x12,
            data_buffer_id=0x234,
            response=ChiRespCode.SC,
        )
        self.assertIn(
            "Resp=0",
            ChiIssueHRspProfile().explain(invalid)[0],
        )

    def test_comp_dbid_response_checks_identifier_widths(self) -> None:
        with self.assertRaisesRegex(ValueError, "data_buffer_id"):
            ChiCompDBIDRespMessage(
                transaction_id=1,
                data_buffer_id=1 << 12,
            )

    def test_dirty_copyback_data_uses_dbid_as_dat_txnid(self) -> None:
        data = (1 << 400) | 0xD177
        message = ChiCopyBackWrDataMessage(
            transaction_id=0x234,
            data=data,
        )
        profile = ChiIssueHDatProfile(data_width=512)
        packet = ChiNetworkPacket.data(
            message,
            source_id=0x07,
            target_id=0x21,
        )

        self.assertEqual(
            ChiDatOpcode.COPY_BACK_WRITE_DATA,
            message.opcode,
        )
        self.assertEqual(0x234, message.semantic_key)
        self.assertEqual(ChiRespCode.UD_PD, message.response)
        self.assertEqual((1 << 64) - 1, message.byte_enable)
        self.assertTrue(message.passes_dirty)
        self.assertTrue(profile.contains(message))
        self.assertFalse(packet.explain_profile(profile))
        self.assertIn(
            "Data exceeds",
            ChiIssueHDatProfile().explain(message)[0],
        )

    def test_copyback_response_and_invalid_data_rules_are_typed(self) -> None:
        invalid_line = ChiCopyBackWrDataMessage(
            transaction_id=3,
            data=0,
            response=ChiRespCode.I,
            byte_enable=0,
        )
        self.assertFalse(invalid_line.passes_dirty)
        self.assertTrue(
            ChiIssueHDatProfile(data_width=512).contains(invalid_line)
        )

        with self.assertRaisesRegex(ValueError, "zero byte enables"):
            ChiCopyBackWrDataMessage(
                transaction_id=3,
                data=1,
                response=ChiRespCode.I,
                byte_enable=0,
            )
        with self.assertRaisesRegex(ValueError, "Resp must"):
            ChiCopyBackWrDataMessage(
                transaction_id=3,
                data=0,
                response=ChiRespCode.I_PD,
                byte_enable=0,
            )


if __name__ == "__main__":
    unittest.main()
