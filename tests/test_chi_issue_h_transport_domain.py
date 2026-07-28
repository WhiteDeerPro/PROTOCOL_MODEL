from __future__ import annotations

import unittest
from dataclasses import dataclass

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelItemKind,
    ChiChannelKind,
    ChiDatLCrdReturn,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiReqLCrdReturn,
    ChiRspLCrdReturn,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiDatChannelSignals,
    ChiDatEnqueue,
    ChiDatTransfer,
    ChiDatTransferKind,
    ChiReqChannelSignals,
    ChiReqEnqueue,
    ChiReqTransfer,
    ChiReqTransferKind,
    ChiRspChannelSignals,
    ChiRspEnqueue,
    ChiRspTransfer,
    ChiRspTransferKind,
)


@dataclass(frozen=True)
class FutureProtocolMessage:
    """Test-only opcode classified by channel rather than a type allowlist."""

    chi_channel: ChiChannelKind
    transaction_id: int = 3
    chi_item_kind: ChiChannelItemKind = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    @property
    def opcode(self) -> int:
        return 0x3F


class ChiIssueHTransportDomainTest(unittest.TestCase):
    def test_same_channel_future_opcode_reaches_neutral_transport_forms(
        self,
    ) -> None:
        request = ChiNetworkPacket.request(
            FutureProtocolMessage(ChiChannelKind.REQ),
            source_id=0x07,
            target_id=0x21,
        )
        data = ChiNetworkPacket.data(
            FutureProtocolMessage(ChiChannelKind.DAT),
            source_id=0x21,
            target_id=0x07,
        )
        response = ChiNetworkPacket.response(
            FutureProtocolMessage(ChiChannelKind.RSP),
            source_id=0x21,
            target_id=0x07,
        )
        request_flit = ChiProtocolFlit(request)
        data_flit = ChiProtocolFlit(data)
        response_flit = ChiProtocolFlit(response)

        self.assertIs(request, ChiReqEnqueue(request).packet)
        self.assertIs(data, ChiDatEnqueue(data).packet)
        self.assertIs(response, ChiRspEnqueue(response).packet)
        ChiReqChannelSignals(True, request_flit)
        ChiDatChannelSignals(True, data_flit)
        ChiRspChannelSignals(True, response_flit)
        self.assertIs(
            ChiReqTransferKind.PROTOCOL,
            ChiReqTransfer("req", request_flit, 0, 0).kind,
        )
        self.assertIs(
            ChiDatTransferKind.PROTOCOL,
            ChiDatTransfer("dat", data_flit, 0).kind,
        )
        self.assertIs(
            ChiRspTransferKind.PROTOCOL,
            ChiRspTransfer("rsp", response_flit, 0).kind,
        )

    def test_domain_rejects_cross_channel_and_classifies_link_flits(
        self,
    ) -> None:
        response = ChiNetworkPacket.response(
            FutureProtocolMessage(ChiChannelKind.RSP),
            source_id=0x21,
            target_id=0x07,
        )
        with self.assertRaisesRegex(TypeError, "REQ link"):
            ChiReqChannelSignals(
                True,
                ChiProtocolFlit(response),
            )

        self.assertIs(
            ChiReqTransferKind.LINK_CREDIT_RETURN,
            ChiReqTransfer("req", ChiReqLCrdReturn(), 0, 0).kind,
        )
        self.assertIs(
            ChiDatTransferKind.LINK_CREDIT_RETURN,
            ChiDatTransfer("dat", ChiDatLCrdReturn(), 0).kind,
        )
        self.assertIs(
            ChiRspTransferKind.LINK_CREDIT_RETURN,
            ChiRspTransfer("rsp", ChiRspLCrdReturn(), 0).kind,
        )


if __name__ == "__main__":
    unittest.main()
