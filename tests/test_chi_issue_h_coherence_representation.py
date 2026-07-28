from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiDatOpcode,
    ChiIssueHDatProfile,
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiIssueHReqProfile,
    ChiMakeUniqueMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiReqOpcode,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompAckMessage,
    ChiIssueHRspProfile,
    ChiRspOpcode,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiIssueHSnpProfile,
    ChiSnpMakeInvalidMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpOpcode,
    ChiSnpUniqueMessage,
)


class ChiIssueHCoherenceRepresentationTest(unittest.TestCase):
    def test_read_shared_is_a_routable_req_message(self) -> None:
        message = ChiReadSharedMessage(
            transaction_id=0x12,
            address=0x8000,
        )
        packet = ChiNetworkPacket.request(
            message,
            source_id=0x07,
            target_id=0x21,
        )

        self.assertEqual(ChiReqOpcode.READ_SHARED, message.opcode)
        self.assertTrue(ChiIssueHReqProfile().contains(message))
        self.assertFalse(packet.explain_profile())

    def test_snoop_response_and_completion_ack_use_distinct_ids(self) -> None:
        response = ChiSnpRespMessage(
            transaction_id=0x100,
            response=ChiRespCode.SC,
        )
        ack = ChiCompAckMessage(transaction_id=0x200)

        self.assertEqual(ChiRspOpcode.SNP_RESP, response.opcode)
        self.assertEqual(ChiRespCode.SC, response.response)
        self.assertEqual(ChiRspOpcode.COMP_ACK, ack.opcode)
        self.assertTrue(ChiIssueHRspProfile().contains(response))
        self.assertTrue(ChiIssueHRspProfile().contains(ack))
        self.assertNotEqual(response.transaction_id, ack.transaction_id)

    def test_non_data_snoop_response_rejects_pass_dirty(self) -> None:
        for response in (
            ChiRespCode.I_PD,
            ChiRespCode.SC_PD,
            ChiRespCode.UC_PD,
            ChiRespCode.SD_PD,
        ):
            with self.subTest(response=response):
                with self.assertRaisesRegex(ValueError, "PassDirty"):
                    ChiSnpRespMessage(
                        transaction_id=1,
                        response=response,
                    )

    def test_read_unique_and_snp_unique_are_typed_routable_messages(
        self,
    ) -> None:
        request = ChiReadUniqueMessage(
            transaction_id=0x13,
            address=0x8000,
        )
        snoop = ChiSnpUniqueMessage(
            transaction_id=0x101,
            address=0x8000,
        )
        packet = ChiNetworkPacket.snoop(
            snoop,
            source_id=0x21,
            target_id=0x08,
        )

        self.assertEqual(ChiReqOpcode.READ_UNIQUE, request.opcode)
        self.assertTrue(ChiIssueHReqProfile().contains(request))
        self.assertEqual(ChiSnpOpcode.SNP_UNIQUE, snoop.opcode)
        self.assertTrue(snoop.do_not_go_to_shared_dirty)
        self.assertFalse(hasattr(snoop, "target_id"))
        self.assertFalse(packet.explain_profile())

    def test_snp_unique_requires_do_not_go_to_shared_dirty(self) -> None:
        message = ChiSnpUniqueMessage(
            transaction_id=1,
            address=0x8000,
            do_not_go_to_shared_dirty=False,
        )

        self.assertIn(
            "DoNotGoToSD",
            ChiIssueHSnpProfile().explain(message)[0],
        )

    def test_make_unique_forms_are_typed_routable_messages(self) -> None:
        request = ChiMakeUniqueMessage(
            transaction_id=0x15,
            address=0x9000,
        )
        snoop = ChiSnpMakeInvalidMessage(
            transaction_id=0x103,
            address=0x9000,
        )
        request_packet = ChiNetworkPacket.request(
            request,
            source_id=0x07,
            target_id=0x21,
        )
        snoop_packet = ChiNetworkPacket.snoop(
            snoop,
            source_id=0x21,
            target_id=0x08,
        )

        self.assertEqual(0x0C, int(ChiReqOpcode.MAKE_UNIQUE))
        self.assertIs(ChiReqOpcode.MAKE_UNIQUE, request.opcode)
        self.assertTrue(ChiIssueHReqProfile().contains(request))
        self.assertFalse(request_packet.explain_profile())
        self.assertEqual(0x0A, int(ChiSnpOpcode.SNP_MAKE_INVALID))
        self.assertIs(ChiSnpOpcode.SNP_MAKE_INVALID, snoop.opcode)
        self.assertTrue(snoop.do_not_go_to_shared_dirty)
        self.assertFalse(snoop.return_to_source)
        self.assertTrue(ChiIssueHSnpProfile().contains(snoop))
        self.assertFalse(snoop_packet.explain_profile())

    def test_mesi_read_and_snoop_are_typed_no_shared_dirty_forms(
        self,
    ) -> None:
        request = ChiReadNotSharedDirtyMessage(
            transaction_id=0x14,
            address=0x8000,
        )
        snoop = ChiSnpNotSharedDirtyMessage(
            transaction_id=0x102,
            address=0x8000,
        )

        self.assertEqual(
            ChiReqOpcode.READ_NOT_SHARED_DIRTY,
            request.opcode,
        )
        self.assertTrue(ChiIssueHReqProfile().contains(request))
        self.assertEqual(
            ChiSnpOpcode.SNP_NOT_SHARED_DIRTY,
            snoop.opcode,
        )
        self.assertTrue(snoop.do_not_go_to_shared_dirty)
        self.assertTrue(ChiIssueHSnpProfile().contains(snoop))

    def test_dirty_snoop_data_is_a_routable_dat_message(self) -> None:
        message = ChiSnpRespDataMessage(
            transaction_id=0x101,
            data=(1 << 400) | 0xD177,
            response=ChiRespCode.I_PD,
        )
        packet = ChiNetworkPacket.data(
            message,
            source_id=0x08,
            target_id=0x21,
        )

        self.assertEqual(ChiDatOpcode.SNP_RESP_DATA, message.opcode)
        self.assertTrue(message.passes_dirty)
        self.assertFalse(
            packet.explain_profile(
                ChiIssueHDatProfile(data_width=512)
            )
        )


if __name__ == "__main__":
    unittest.main()
