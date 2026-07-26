from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiPCrdGrantMessage,
    ChiRetryAckMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiLinkActivationPhase,
    ChiLinkEndpointRef,
    ChiRspChannelProfile,
    ChiRspDrain,
    ChiRspEnqueue,
    ChiRspPathTick,
    ChiRspPointToPointSession,
    ChiRspTransferKind,
    ChiTransportLink,
    ChiTransportLinkProfile,
)


class ChiIssueHRspPointToPointTest(unittest.TestCase):
    def make_path(
        self,
        *,
        tx_capacity: int = 2,
        rx_capacity: int = 2,
        credit_capacity: int = 1,
    ) -> ChiRspPointToPointSession:
        profile = ChiTransportLinkProfile(
            request=None,
            data=None,
            response=ChiRspChannelProfile(
                representation=ChiIssueHRspProfile(node_id_width=7),
                credit_capacity=credit_capacity,
                observation="home_to_rn.rsp",
            ),
            clock="chi_clk",
            activation_observation="home_to_rn.active",
        )
        link = ChiTransportLink(
            "home_to_rn_rsp",
            ChiLinkEndpointRef("home", "txrsp"),
            ChiLinkEndpointRef("rn_i", "rxrsp"),
            profile,
        )
        return ChiRspPointToPointSession(
            link,
            transmitter_capacity=tx_capacity,
            receiver_capacity=rx_capacity,
        )

    @staticmethod
    def retry_ack(transaction_id: int = 3) -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiRetryAckMessage(
                transaction_id=transaction_id,
                protocol_credit_type=2,
            ),
            source_id=0x21,
            target_id=0x07,
        )

    @staticmethod
    def credit_grant() -> ChiNetworkPacket:
        return ChiNetworkPacket.response(
            ChiPCrdGrantMessage(protocol_credit_type=2),
            source_id=0x21,
            target_id=0x07,
        )

    def apply(self, path, state, action):
        transition = path.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_retry_ack_and_pcredit_grant_share_rsp_transport(self) -> None:
        path = self.make_path()
        state = path.initial_state()
        state = self.apply(
            path, state, ChiRspEnqueue(self.retry_ack())
        ).state
        state = self.apply(
            path, state, ChiRspEnqueue(self.credit_grant())
        ).state

        activating = self.apply(path, state, ChiRspPathTick())
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            activating.emissions[0].phase,
        )
        running = self.apply(path, activating.state, ChiRspPathTick())
        self.assertTrue(running.emissions[0].grant)
        self.assertIsNone(running.emissions[0].transfer)

        first = self.apply(path, running.state, ChiRspPathTick())
        self.assertIsInstance(
            first.emissions[0].transfer.flit.packet.message,
            ChiRetryAckMessage,
        )
        self.assertEqual(
            ChiRspTransferKind.PROTOCOL,
            first.emissions[0].transfer.kind,
        )
        second = self.apply(path, first.state, ChiRspPathTick())
        self.assertIsInstance(
            second.emissions[0].transfer.flit.packet.message,
            ChiPCrdGrantMessage,
        )
        self.assertEqual(0, second.state.transmitter.depth)
        self.assertEqual(2, second.state.receiver.depth)

    def test_same_frame_grant_does_not_authorize_rsp_transfer(self) -> None:
        path = self.make_path()
        state = path.initial_state()
        state = self.apply(
            path, state, ChiRspEnqueue(self.retry_ack())
        ).state
        state = self.apply(path, state, ChiRspPathTick()).state

        running = self.apply(path, state, ChiRspPathTick())

        self.assertTrue(running.emissions[0].grant)
        self.assertIsNone(running.emissions[0].transfer)
        sent = self.apply(path, running.state, ChiRspPathTick())
        self.assertIsNotNone(sent.emissions[0].transfer)

    def test_full_rsp_fifo_reports_backpressure_without_mutation(self) -> None:
        path = self.make_path(tx_capacity=1)
        state = path.initial_state()
        state = self.apply(
            path, state, ChiRspEnqueue(self.retry_ack(1))
        ).state

        blocked = path.step(state, ChiRspEnqueue(self.retry_ack(2)))

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertIn("queue is full", blocked.blocked.reason)

    def test_unused_rsp_credit_is_returned_before_stop(self) -> None:
        path = self.make_path()
        state = path.initial_state()
        state = self.apply(path, state, ChiRspPathTick()).state
        state = self.apply(path, state, ChiRspPathTick()).state
        self.assertEqual(1, state.link.response.usable_credits)

        deactivating = self.apply(
            path, state, ChiRspPathTick(active=False)
        )
        self.assertEqual(
            ChiRspTransferKind.LINK_CREDIT_RETURN,
            deactivating.emissions[0].transfer.kind,
        )
        stopped = self.apply(
            path, deactivating.state, ChiRspPathTick(active=False)
        )
        self.assertEqual(
            ChiLinkActivationPhase.STOP,
            stopped.emissions[0].phase,
        )
        self.assertTrue(path.is_quiescent(stopped.state))

    def test_representation_checks_node_width_and_grant_txnid(self) -> None:
        grant = self.credit_grant()
        self.assertEqual(0, grant.message.transaction_id)
        profile = ChiIssueHRspProfile(node_id_width=7)
        self.assertEqual((), grant.explain_profile(profile))
        invalid = ChiNetworkPacket.response(
            ChiRetryAckMessage(
                transaction_id=1,
                protocol_credit_type=0,
            ),
            source_id=0x21,
            target_id=0x80,
        )
        self.assertTrue(
            any("TgtID" in item for item in invalid.explain_profile(profile))
        )

        path = self.make_path()
        failed = path.step(path.initial_state(), ChiRspEnqueue(invalid))
        self.assertIsNotNone(failed.fault)
        self.assertIn("NodeID", failed.fault.reason)

    def test_drain_keeps_protocol_interpretation_outside_transport(self) -> None:
        path = self.make_path(rx_capacity=1)
        state = path.initial_state()
        state = self.apply(
            path, state, ChiRspEnqueue(self.credit_grant())
        ).state
        for _ in range(3):
            state = self.apply(path, state, ChiRspPathTick()).state
        self.assertEqual(1, state.receiver.depth)

        state = self.apply(path, state, ChiRspDrain()).state

        self.assertEqual(0, state.receiver.depth)


if __name__ == "__main__":
    unittest.main()
