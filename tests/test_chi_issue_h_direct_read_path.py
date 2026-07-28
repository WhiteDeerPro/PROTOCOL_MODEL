from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiDatChannelProfile,
    ChiDatDrain,
    ChiDatEnqueue,
    ChiDatPathTick,
    ChiDatPointToPointSession,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiReqDrain,
    ChiReqEnqueue,
    ChiReqPathTick,
    ChiReqPointToPointSession,
    ChiTransportLink,
    ChiTransportLinkProfile,
)


class ChiIssueHDirectReadPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=1,
        )
        self.requester = ChiReadNoSnpDirectLedger(
            "rn_i.reads", self.profile
        )
        self.home = ChiDirectHomeNode(
            "home",
            self.profile,
            lambda request: 0xC000_0000 | request.address,
            request_capacity=1,
        )
        self.request_path = ChiReqPointToPointSession(
            ChiTransportLink(
                "rn_to_home",
                ChiLinkEndpointRef("rn_i", "txlink"),
                ChiLinkEndpointRef("home", "rxlink"),
                ChiTransportLinkProfile(
                    request=ChiReqChannelProfile(
                        representation=ChiIssueHReqProfile(),
                        credit_capacities=(1,),
                        observation="rn_to_home.req",
                    ),
                    data=None,
                    clock="chi_clk",
                    activation_observation="rn_to_home.active",
                ),
            ),
            transmitter_capacity=1,
            receiver_capacities_by_plane=(1,),
        )
        self.data_path = ChiDatPointToPointSession(
            ChiTransportLink(
                "home_to_rn",
                ChiLinkEndpointRef("home", "txlink"),
                ChiLinkEndpointRef("rn_i", "rxlink"),
                ChiTransportLinkProfile(
                    request=None,
                    data=ChiDatChannelProfile(
                        representation=ChiIssueHDatProfile(data_width=128),
                        credit_capacity=1,
                        observation="home_to_rn.dat",
                    ),
                    clock="chi_clk",
                    activation_observation="home_to_rn.active",
                ),
            ),
            transmitter_capacity=1,
            receiver_capacity=1,
        )

    @staticmethod
    def request() -> ChiReadNoSnpMessage:
        return ChiReadNoSnpMessage(
            transaction_id=3,
            address=0x4020,
            size=3,
            order=0,
            allow_retry=True,
            protocol_credit_type=0,
            expect_completion_ack=False,
            memory_attributes=0,
        )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_request_and_comp_data_cross_two_directed_links(self) -> None:
        request = self.request()
        requester_state = self.apply(
            self.requester,
            self.requester.initial_state(),
            ChiReadNoSnpIssue(request),
        ).state

        request_path_state = self.apply(
            self.request_path,
            self.request_path.initial_state(),
            ChiReqEnqueue(
                ChiNetworkPacket.request(
                    request,
                    source_id=self.profile.requester_node_id,
                    target_id=self.profile.home_node_id,
                )
            ),
        ).state
        data_path_state = self.data_path.initial_state()
        request_observations = []
        data_observations = []
        for _ in range(3):
            request_step = self.apply(
                self.request_path,
                request_path_state,
                ChiReqPathTick(),
            )
            data_step = self.apply(
                self.data_path,
                data_path_state,
                ChiDatPathTick(),
            )
            request_path_state = request_step.state
            data_path_state = data_step.state
            request_observations.extend(request_step.emissions)
            data_observations.extend(data_step.emissions)

        captured_request = (
            request_path_state.receiver.captured[0].flit.packet.message
        )
        self.assertEqual(request, captured_request)
        self.assertEqual(1, request_observations[-1].rx_depth_after)

        home_state = self.apply(
            self.home,
            self.home.initial_state(),
            ChiDirectHomeAccept(captured_request),
        ).state
        request_path_state = self.apply(
            self.request_path,
            request_path_state,
            ChiReqDrain(),
        ).state
        serviced = self.apply(
            self.home, home_state, ChiDirectHomeService()
        )
        response = serviced.emissions[0]

        data_path_state = self.apply(
            self.data_path,
            data_path_state,
            ChiDatEnqueue(
                ChiNetworkPacket.data(
                    response,
                    source_id=self.profile.home_node_id,
                    target_id=self.profile.requester_node_id,
                )
            ),
        ).state
        request_path_state = self.apply(
            self.request_path,
            request_path_state,
            ChiReqPathTick(active=False),
        ).state
        data_step = self.apply(
            self.data_path,
            data_path_state,
            ChiDatPathTick(),
        )
        data_path_state = data_step.state
        data_observations.extend(data_step.emissions)

        captured_response = (
            data_path_state.receiver.captured[0].flit.packet.message
        )
        completed = self.apply(
            self.requester,
            requester_state,
            ChiReadNoSnpComplete(captured_response),
        )
        data_path_state = self.apply(
            self.data_path,
            data_path_state,
            ChiDatDrain(),
        ).state

        self.assertEqual(0xC000_4020, completed.emissions[0].data)
        self.assertEqual(2, captured_response.data_id)
        self.assertTrue(self.requester.is_quiescent(completed.state))
        self.assertEqual(1, serviced.state.completed_count)
        self.assertEqual(1, data_observations[-1].rx_depth_after)
        self.assertEqual(0, request_path_state.receiver.depth)
        self.assertEqual(0, data_path_state.receiver.depth)

        request_path_state = self.apply(
            self.request_path,
            request_path_state,
            ChiReqPathTick(active=False),
        ).state
        data_path_state = self.apply(
            self.data_path,
            data_path_state,
            ChiDatPathTick(active=False),
        ).state
        data_path_state = self.apply(
            self.data_path,
            data_path_state,
            ChiDatPathTick(active=False),
        ).state
        self.assertTrue(self.request_path.is_quiescent(request_path_state))
        self.assertTrue(self.data_path.is_quiescent(data_path_state))


if __name__ == "__main__":
    unittest.main()
