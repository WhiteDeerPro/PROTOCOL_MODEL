from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiExactNodeRoute,
    ChiRouterReceive,
    ChiRouterService,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompDataMessage,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiReadNoSnpMessage,
)


class ChiIssueHStoreForwardRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_rn", "from_home"),
            egress_ports=("to_rn", "to_home"),
            routes=(
                ChiExactNodeRoute(
                    0x21,
                    "to_home",
                    frozenset((ChiChannelKind.REQ,)),
                ),
                ChiExactNodeRoute(
                    0x07,
                    "to_rn",
                    frozenset(
                        (ChiChannelKind.RSP, ChiChannelKind.DAT)
                    ),
                ),
            ),
            queue_capacity=1,
        )

    @staticmethod
    def request(transaction_id: int) -> ChiReadNoSnpMessage:
        return ChiReadNoSnpMessage(
            transaction_id=transaction_id,
            address=0x4000 + 8 * transaction_id,
            size=3,
            allow_retry=True,
            protocol_credit_type=0,
        )

    @staticmethod
    def data(transaction_id: int) -> ChiCompDataMessage:
        return ChiCompDataMessage(
            transaction_id=transaction_id,
            home_node_id=0x21,
            data=0xA500_0000 | transaction_id,
        )

    def apply(self, state, action):
        transition = self.router.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_req_and_dat_route_by_channel_and_target_without_rewrite(self) -> None:
        state = self.router.initial_state()
        request_packet = ChiNetworkPacket.request(
            self.request(3), source_id=0x07, target_id=0x21
        )
        state = self.apply(
            state,
            ChiRouterReceive(
                "from_rn",
                request_packet,
                resource_plane=0,
                lineage=("rn_i.txreq",),
            ),
        ).state
        forwarded = self.apply(
            state, ChiRouterService(ChiChannelKind.REQ, "to_home")
        )
        request_entry = forwarded.emissions[0]
        self.assertEqual("from_rn", request_entry.ingress_port)
        self.assertEqual("to_home", request_entry.egress_port)
        self.assertIs(request_packet, request_entry.packet)
        self.assertEqual(("rn_i.txreq",), request_entry.lineage)

        data_packet = ChiNetworkPacket.data(
            self.data(3), source_id=0x21, target_id=0x07
        )
        state = self.apply(
            forwarded.state,
            ChiRouterReceive(
                "from_home", data_packet, lineage=("home.txdat",)
            ),
        ).state
        returned = self.apply(
            state, ChiRouterService(ChiChannelKind.DAT, "to_rn")
        )
        self.assertIs(data_packet, returned.emissions[0].packet)
        self.assertTrue(self.router.is_quiescent(returned.state))

    def test_full_channel_egress_queue_blocks_without_mutation(self) -> None:
        state = self.router.initial_state()
        state = self.apply(
            state,
            ChiRouterReceive(
                "from_rn",
                ChiNetworkPacket.request(
                    self.request(1), source_id=0x07, target_id=0x21
                ),
            ),
        ).state

        blocked = self.router.step(
            state,
            ChiRouterReceive(
                "from_rn",
                ChiNetworkPacket.request(
                    self.request(2), source_id=0x07, target_id=0x21
                ),
            ),
        )

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertEqual(1, state.depth)
        self.assertIn("is full", blocked.blocked.reason)

    def test_router_routes_current_rsp_payload_without_rewrite(self) -> None:
        packet = ChiNetworkPacket.response(
            ChiPCrdGrantMessage(
                protocol_credit_type=4,
            ),
            source_id=0x21,
            target_id=0x07,
        )
        state = self.apply(
            self.router.initial_state(),
            ChiRouterReceive(
                "from_home", packet, lineage=("pcredit",)
            ),
        ).state

        forwarded = self.apply(
            state, ChiRouterService(ChiChannelKind.RSP, "to_rn")
        )

        self.assertIs(packet, forwarded.emissions[0].packet)

    def test_unknown_target_is_a_local_route_fault(self) -> None:
        request = self.request(3)
        packet = ChiNetworkPacket.request(
            ChiReadNoSnpMessage(
                transaction_id=request.transaction_id,
                address=request.address,
                size=request.size,
            ),
            source_id=0x07,
            target_id=0x22,
        )

        failed = self.router.step(
            self.router.initial_state(),
            ChiRouterReceive("from_rn", packet),
        )

        self.assertIsNotNone(failed.fault)
        self.assertIn("exactly one", failed.fault.reason)

    def test_known_payload_cannot_be_disguised_as_another_channel(self) -> None:
        with self.assertRaisesRegex(ValueError, "REQ protocol message"):
            ChiNetworkPacket(
                ChiChannelKind.RSP, self.request(3), 0x07, 0x21
            )
        with self.assertRaisesRegex(ValueError, "DAT protocol message"):
            ChiNetworkPacket(
                ChiChannelKind.RSP, self.data(3), 0x21, 0x07
            )


if __name__ == "__main__":
    unittest.main()
