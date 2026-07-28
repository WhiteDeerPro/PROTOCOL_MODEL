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
    ChiIssueHSnpProfile,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiSnpSharedMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiNetworkCaptureToRouter,
    ChiNetworkEnqueue,
    ChiNetworkRouterToConnection,
    ChiNetworkTick,
    ChiTransportNetworkSession,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiSnpChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.system import SystemProtocolBuilder, VirtualDutPortRef
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHSnpNetworkTest(unittest.TestCase):
    HOME_NODE_ID = 0x21
    REQUESTER_NODE_ID = 0x07

    @staticmethod
    def transport_port(
        name: str,
        direction: TransportDirection,
    ) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    @staticmethod
    def snp_profile(name: str) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=None,
            response=None,
            data=None,
            snoop=ChiSnpChannelProfile(
                representation=ChiIssueHSnpProfile(),
                credit_capacity=1,
                observation=f"{name}.snp",
            ),
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    @classmethod
    def build_network(cls) -> tuple[
        ChiTransportNetworkSession,
        ChiStoreForwardRouterNode,
    ]:
        builder = SystemProtocolBuilder("chi_snp_home_xp_requester")
        builder.add_dut(
            VirtualDut(
                "home",
                {
                    "tx_snp": cls.transport_port(
                        "tx_snp",
                        TransportDirection.TRANSMIT,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "xp0",
                {
                    "from_home": cls.transport_port(
                        "from_home",
                        TransportDirection.RECEIVE,
                    ),
                    "to_requester": cls.transport_port(
                        "to_requester",
                        TransportDirection.TRANSMIT,
                    ),
                },
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
            )
        )
        builder.add_dut(
            VirtualDut(
                "requester",
                {
                    "rx_snp": cls.transport_port(
                        "rx_snp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        builder.connect_transport(
            "home_to_xp",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("home", "tx_snp"),
            VirtualDutPortRef("xp0", "from_home"),
            profile=cls.snp_profile("home_to_xp"),
        )
        builder.connect_transport(
            "xp_to_requester",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("xp0", "to_requester"),
            VirtualDutPortRef("requester", "rx_snp"),
            profile=cls.snp_profile("xp_to_requester"),
        )
        router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_home",),
            egress_ports=("to_requester",),
            routes=(
                ChiExactNodeRoute(
                    cls.REQUESTER_NODE_ID,
                    "to_requester",
                    frozenset((ChiChannelKind.SNP,)),
                ),
            ),
            queue_capacity=1,
        )
        return (
            ChiTransportNetworkSession(
                builder.build().elaborate(),
                routers={"xp0": router},
            ),
            router,
        )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def tick(
        self,
        network: ChiTransportNetworkSession,
        state,
        connection: str,
        count: int = 3,
    ):
        transitions = []
        for _ in range(count):
            transition = self.apply(
                network,
                state,
                ChiNetworkTick(connection),
            )
            transitions.append(transition)
            state = transition.state
        return state, transitions

    def test_snoop_packet_crosses_xp_without_losing_network_route(self) -> None:
        network, _ = self.build_network()
        message = ChiSnpSharedMessage(
            transaction_id=9,
            address=0x8000,
            return_to_source=True,
        )
        packet = ChiNetworkPacket.snoop(
            message,
            source_id=self.HOME_NODE_ID,
            target_id=self.REQUESTER_NODE_ID,
        )
        state = self.apply(
            network,
            network.initial_state(),
            ChiNetworkEnqueue(
                "home_to_xp",
                packet,
                lineage=("home.snoop_select",),
            ),
        ).state

        state, first_hop = self.tick(network, state, "home_to_xp")
        transfer = first_hop[-1].emissions[0].detail.transfers[
            ChiChannelKind.SNP
        ]
        self.assertIsInstance(transfer.flit, ChiProtocolFlit)
        self.assertIs(packet, transfer.flit.packet)

        state = self.apply(
            network,
            state,
            ChiNetworkCaptureToRouter(
                "home_to_xp",
                ChiChannelKind.SNP,
            ),
        ).state
        state = self.apply(
            network,
            state,
            ChiNetworkRouterToConnection(
                "xp_to_requester",
                ChiChannelKind.SNP,
            ),
        ).state
        state, _ = self.tick(network, state, "xp_to_requester")

        delivery = network.peek_delivery(
            state,
            "xp_to_requester",
            ChiChannelKind.SNP,
        )
        self.assertIsNotNone(delivery)
        assert delivery is not None
        self.assertIs(packet, delivery.packet)
        self.assertIs(message, delivery.packet.message)
        self.assertEqual(self.HOME_NODE_ID, delivery.packet.source_id)
        self.assertEqual(self.REQUESTER_NODE_ID, delivery.packet.target_id)
        self.assertFalse(hasattr(message, "target_id"))
        self.assertEqual("home.snoop_select", delivery.lineage[0])

    def test_fanout_requires_two_explicit_packets_not_router_multicast(self) -> None:
        message = ChiSnpSharedMessage(
            transaction_id=10,
            address=0xA000,
        )
        first = ChiNetworkPacket.snoop(
            message,
            source_id=self.HOME_NODE_ID,
            target_id=0x07,
        )
        second = ChiNetworkPacket.snoop(
            message,
            source_id=self.HOME_NODE_ID,
            target_id=0x08,
        )
        router = ChiStoreForwardRouterNode(
            "xp_fanout",
            ingress_ports=("from_home",),
            egress_ports=("to_rn0", "to_rn1"),
            routes=(
                ChiExactNodeRoute(
                    0x07,
                    "to_rn0",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    0x08,
                    "to_rn1",
                    frozenset((ChiChannelKind.SNP,)),
                ),
            ),
            queue_capacity=1,
        )
        state = router.initial_state()

        for packet in (first, second):
            state = self.apply(
                router,
                state,
                ChiRouterReceive("from_home", packet),
            ).state

        first_forward = self.apply(
            router,
            state,
            ChiRouterService(ChiChannelKind.SNP, "to_rn0"),
        )
        second_forward = self.apply(
            router,
            first_forward.state,
            ChiRouterService(ChiChannelKind.SNP, "to_rn1"),
        )

        self.assertIs(message, first_forward.emissions[0].packet.message)
        self.assertIs(message, second_forward.emissions[0].packet.message)
        self.assertIs(first, first_forward.emissions[0].packet)
        self.assertIs(second, second_forward.emissions[0].packet)
        self.assertEqual(2, second_forward.state.accepted_count)
        self.assertEqual(2, second_forward.state.forwarded_count)


if __name__ == "__main__":
    unittest.main()
