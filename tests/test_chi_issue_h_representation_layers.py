from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiReadNoSnpMessage,
    ChiReqLCrdReturn,
    ChiRetryAckMessage,
    ChiSnpSharedMessage,
)


class ChiIssueHRepresentationLayersTest(unittest.TestCase):
    def test_message_packet_and_flit_have_distinct_authorities(self) -> None:
        message = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0x4000,
        )
        packet = ChiNetworkPacket.request(
            message,
            source_id=0x07,
            target_id=0x21,
        )
        flit = ChiProtocolFlit(packet)

        self.assertFalse(hasattr(message, "source_id"))
        self.assertFalse(hasattr(message, "target_id"))
        self.assertIs(message, packet.message)
        self.assertEqual(0x07, packet.source_id)
        self.assertEqual(0x21, packet.target_id)
        self.assertFalse(hasattr(packet, "payload"))
        self.assertIs(packet, flit.packet)
        self.assertFalse(hasattr(flit, "payload"))
        self.assertIs(ChiChannelKind.REQ, flit.chi_channel)

    def test_one_snoop_message_can_be_replicated_to_several_targets(self) -> None:
        message = ChiSnpSharedMessage(
            transaction_id=9,
            address=0x8000,
        )

        first = ChiNetworkPacket.snoop(
            message,
            source_id=0x21,
            target_id=0x07,
        )
        second = ChiNetworkPacket.snoop(
            message,
            source_id=0x21,
            target_id=0x08,
        )

        self.assertIs(first.message, second.message)
        self.assertNotEqual(first.target_id, second.target_id)
        self.assertFalse(hasattr(message, "source_id"))
        self.assertFalse(hasattr(message, "target_id"))

    def test_packetization_identity_is_explicit_and_bounded(self) -> None:
        message = ChiReadNoSnpMessage(
            transaction_id=4,
            address=0x4000,
        )
        packet = ChiNetworkPacket.request(
            message,
            source_id=1,
            target_id=2,
            packet_index=1,
            packet_count=2,
        )

        self.assertEqual((1, 2), (packet.packet_index, packet.packet_count))
        with self.assertRaisesRegex(ValueError, "smaller"):
            ChiNetworkPacket.request(
                message,
                source_id=1,
                target_id=2,
                packet_index=2,
                packet_count=2,
            )

    def test_packet_rejects_channel_mismatch_and_maintenance_flit(self) -> None:
        response = ChiRetryAckMessage(
            transaction_id=3,
            protocol_credit_type=1,
        )

        with self.assertRaisesRegex(ValueError, "RSP.*REQ"):
            ChiNetworkPacket.request(
                response,
                source_id=0x21,
                target_id=0x07,
            )
        with self.assertRaisesRegex(TypeError, "link-maintenance"):
            ChiNetworkPacket.request(
                ChiReqLCrdReturn(),
                source_id=0x07,
                target_id=0x21,
            )

    def test_packet_profile_checks_message_and_route_widths(self) -> None:
        message = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0x4000,
        )
        packet = ChiNetworkPacket.request(
            message,
            source_id=0x07,
            target_id=0x80,
        )

        self.assertIn("TgtID", packet.explain_profile()[0])


if __name__ == "__main__":
    unittest.main()
