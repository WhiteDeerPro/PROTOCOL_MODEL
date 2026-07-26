from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
    ChiRetryAckMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiConnectionDrain,
    ChiConnectionEnqueue,
    ChiConnectionTick,
    ChiDatChannelProfile,
    ChiLinkActivationPhase,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiTransportConnectionSession,
    ChiTransportLink,
    ChiTransportLinkProfile,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiNetworkDrain,
    ChiNetworkEnqueue,
    ChiNetworkTick,
    ChiTransportNetworkSession,
)
from protocol_model.system import SystemProtocolBuilder, VirtualDutPortRef
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHMultiChannelConnectionTest(unittest.TestCase):
    @staticmethod
    def profile() -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                representation=ChiIssueHReqProfile(),
                credit_capacities=(1,),
                observation="mixed.req",
            ),
            response=ChiRspChannelProfile(
                representation=ChiIssueHRspProfile(),
                credit_capacity=1,
                observation="mixed.rsp",
            ),
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=1,
                observation="mixed.dat",
            ),
            clock="chi_clk",
            activation_observation="mixed.active",
        )

    @classmethod
    def make_connection(cls) -> ChiTransportConnectionSession:
        return ChiTransportConnectionSession(
            ChiTransportLink(
                "mixed",
                ChiLinkEndpointRef("source", "tx"),
                ChiLinkEndpointRef("target", "rx"),
                cls.profile(),
            ),
            transmitter_capacity=2,
        )

    @staticmethod
    def request() -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            ChiReadNoSnpMessage(
                transaction_id=3,
                address=0x4000,
                size=3,
            ),
            source_id=0x07,
            target_id=0x21,
        )

    @staticmethod
    def response() -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiRetryAckMessage(
                transaction_id=3,
                protocol_credit_type=2,
            ),
            source_id=0x21,
            target_id=0x07,
        )

    @staticmethod
    def data() -> ChiNetworkPacket:
        return ChiNetworkPacket.data(
            ChiCompDataMessage(
                transaction_id=3,
                home_node_id=0x21,
                data=0xA5,
                data_id=0,
            ),
            source_id=0x21,
            target_id=0x07,
        )

    def apply(self, connection, state, action):
        transition = connection.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_three_channels_share_one_activation_and_atomic_frame(self) -> None:
        connection = self.make_connection()
        state = connection.initial_state()
        for packet in (self.request(), self.response(), self.data()):
            state = self.apply(
                connection,
                state,
                ChiConnectionEnqueue(packet),
            ).state

        activating = self.apply(
            connection, state, ChiConnectionTick()
        )
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            activating.emissions[0].phase,
        )
        granting = self.apply(
            connection, activating.state, ChiConnectionTick()
        )
        self.assertEqual(
            {
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            },
            set(granting.emissions[0].grants_by_channel),
        )
        self.assertEqual({}, dict(granting.emissions[0].transfers))

        transferred = self.apply(
            connection, granting.state, ChiConnectionTick()
        )
        observation = transferred.emissions[0]
        self.assertEqual(
            {
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            },
            set(observation.transfers),
        )
        self.assertEqual(
            1,
            transferred.state.link.activation.epoch,
            "one Link authority owns one activation epoch",
        )
        self.assertTrue(
            all(
                transferred.state.transmitters[channel].depth == 0
                for channel in connection.channels
            )
        )
        self.assertTrue(
            all(
                transferred.state.receivers[channel].depth == 1
                for channel in connection.channels
            )
        )

    def test_channel_drain_and_capacity_are_independent(self) -> None:
        connection = self.make_connection()
        state = connection.initial_state()
        for packet in (self.request(), self.response()):
            state = self.apply(
                connection,
                state,
                ChiConnectionEnqueue(packet),
            ).state
        for _ in range(3):
            state = self.apply(
                connection, state, ChiConnectionTick()
            ).state

        state = self.apply(
            connection,
            state,
            ChiConnectionDrain(ChiChannelKind.REQ),
        ).state
        self.assertEqual(
            0, state.receivers[ChiChannelKind.REQ].depth
        )
        self.assertEqual(
            1, state.receivers[ChiChannelKind.RSP].depth
        )

    def test_system_connection_carries_all_enabled_channels(self) -> None:
        builder = SystemProtocolBuilder("chi_multi_channel")
        builder.add_dut(
            VirtualDut(
                "source",
                {
                    "tx": TransportPort(
                        "tx",
                        CHI_ISSUE_H_TRANSPORT_FAMILY,
                        TransportDirection.TRANSMIT,
                        clock_domain="chi_clk",
                    )
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "target",
                {
                    "rx": TransportPort(
                        "rx",
                        CHI_ISSUE_H_TRANSPORT_FAMILY,
                        TransportDirection.RECEIVE,
                        clock_domain="chi_clk",
                    )
                },
            )
        )
        builder.connect_transport(
            "mixed",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("source", "tx"),
            VirtualDutPortRef("target", "rx"),
            profile=self.profile(),
        )
        network = ChiTransportNetworkSession(
            builder.build().elaborate(),
            transmitter_capacity_by_connection={"mixed": 2},
        )
        state = network.initial_state()
        for label, packet in (
            ("request", self.request()),
            ("response", self.response()),
            ("data", self.data()),
        ):
            transition = network.step(
                state,
                ChiNetworkEnqueue(
                    "mixed", packet, lineage=(label,)
                ),
            )
            self.assertIsNone(transition.fault)
            self.assertIsNone(transition.blocked)
            state = transition.state
        for _ in range(3):
            transition = network.step(state, ChiNetworkTick("mixed"))
            self.assertIsNone(transition.fault)
            state = transition.state

        with self.assertRaisesRegex(ValueError, "several captured"):
            network.peek_delivery(state, "mixed")
        for channel in (
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
            ChiChannelKind.DAT,
        ):
            delivery = network.peek_delivery(
                state, "mixed", channel
            )
            self.assertIsNotNone(delivery)
            assert delivery is not None
            self.assertIs(channel, delivery.packet.channel)

        drained = network.step(
            state,
            ChiNetworkDrain("mixed", ChiChannelKind.RSP),
        )
        self.assertIsNone(drained.fault)
        self.assertIsNone(
            network.peek_delivery(
                drained.state, "mixed", ChiChannelKind.RSP
            )
        )
        self.assertIsNotNone(
            network.peek_delivery(
                drained.state, "mixed", ChiChannelKind.REQ
            )
        )


if __name__ == "__main__":
    unittest.main()
