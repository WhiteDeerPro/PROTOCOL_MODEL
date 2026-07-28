from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import ClassVar

from protocol_model.protocols.amba.chi.issue_h.representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelItemKind,
    ChiChannelKind,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
    ChiReqLCrdReturn,
)


@dataclass(frozen=True)
class FutureReqProtocolMessage:
    """A test-only REQ opcode unknown to the current REQ profile."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int

    @property
    def opcode(self) -> int:
        return 0x3F


class FutureReqProfile:
    channel = ChiChannelKind.REQ

    @staticmethod
    def explain(message: object) -> tuple[str, ...]:
        if not isinstance(message, FutureReqProtocolMessage):
            return ("expected the test-only REQ message",)
        return ()


class ChiIssueHRepresentationDomainTest(unittest.TestCase):
    def test_domain_separates_protocol_and_link_maintenance_flits(self) -> None:
        request = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0x4000,
        )

        protocol = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(request)
        maintenance = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(
            ChiReqLCrdReturn()
        )

        self.assertIs(ChiChannelKind.REQ, protocol.channel)
        self.assertTrue(protocol.is_message)
        self.assertIs(ChiChannelKind.REQ, maintenance.channel)
        self.assertTrue(maintenance.is_link_maintenance)
        self.assertTrue(
            CHI_ISSUE_H_CHANNEL_DOMAIN.profile_contains(request)
        )
        self.assertIn(
            "hop-local",
            CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(
                ChiReqLCrdReturn()
            )[0],
        )

    def test_new_req_message_needs_no_packet_allowlist_change(self) -> None:
        message = FutureReqProtocolMessage(transaction_id=9)

        packet = ChiNetworkPacket.request(
            message,
            source_id=0x07,
            target_id=0x21,
        )

        self.assertIs(message, packet.message)
        self.assertIs(ChiChannelKind.REQ, packet.channel)
        self.assertFalse(
            CHI_ISSUE_H_CHANNEL_DOMAIN.profile_contains(message)
        )
        self.assertTrue(
            CHI_ISSUE_H_CHANNEL_DOMAIN.profile_contains(
                message,
                FutureReqProfile(),
            )
        )

    def test_network_packet_rejects_hop_local_link_flit(self) -> None:
        with self.assertRaisesRegex(TypeError, "link-maintenance"):
            ChiNetworkPacket.request(
                ChiReqLCrdReturn(),
                source_id=0x07,
                target_id=0x21,
            )


if __name__ == "__main__":
    unittest.main()
