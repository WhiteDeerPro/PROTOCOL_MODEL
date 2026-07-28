from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiIssueHReqProfile,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiLinkActivationPhase,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiReqDrain,
    ChiReqEnqueue,
    ChiReqPathTick,
    ChiReqTransferKind,
    ChiTransportLink,
    ChiTransportLinkProfile,
    ChiReqPointToPointSession,
)


class ChiIssueHPointToPointPathTest(unittest.TestCase):
    def setUp(self) -> None:
        profile = ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                representation=ChiIssueHReqProfile(),
                credit_capacities=(1,),
                observation="rn_to_home.req",
            ),
            clock="chi_clk",
            activation_observation="rn_to_home.active",
        )
        self.link = ChiTransportLink(
            "rn_to_home",
            ChiLinkEndpointRef("rn_i", "txlink"),
            ChiLinkEndpointRef("home", "rxlink"),
            profile,
        )
        self.path = ChiReqPointToPointSession(
            self.link,
            transmitter_capacity=2,
            receiver_capacities_by_plane=(2,),
        )

    @staticmethod
    def read(transaction_id: int) -> ChiNetworkPacket:
        return ChiNetworkPacket.request(
            ChiReadNoSnpMessage(
                transaction_id=transaction_id,
                address=0x4000 + 8 * transaction_id,
                size=3,
                allow_retry=True,
                memory_attributes=0,
            ),
            source_id=0x07,
            target_id=0x21,
        )

    def apply(self, state, action):
        transition = self.path.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_two_requests_cross_a_finite_node_link_node_path(self) -> None:
        state = self.path.initial_state()
        state = self.apply(state, ChiReqEnqueue(self.read(1))).state
        state = self.apply(state, ChiReqEnqueue(self.read(2))).state

        activate = self.apply(state, ChiReqPathTick())
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            activate.emissions[0].phase,
        )
        self.assertIsNone(activate.emissions[0].transfer)

        run_entry = self.apply(activate.state, ChiReqPathTick())
        self.assertEqual(ChiLinkActivationPhase.RUN, run_entry.emissions[0].phase)
        self.assertEqual((True,), run_entry.emissions[0].grants_by_plane)
        self.assertIsNone(run_entry.emissions[0].transfer)

        first = self.apply(run_entry.state, ChiReqPathTick())
        self.assertEqual((True,), first.emissions[0].grants_by_plane)
        self.assertEqual(
            ChiReqTransferKind.PROTOCOL,
            first.emissions[0].transfer.kind,
        )
        self.assertEqual(1, first.state.transmitter.depth)
        self.assertEqual(1, first.state.receiver.depth)
        self.assertEqual((1,), first.state.receiver.reserved_by_plane)

        second = self.apply(first.state, ChiReqPathTick())
        self.assertEqual((False,), second.emissions[0].grants_by_plane)
        self.assertEqual(0, second.state.transmitter.depth)
        self.assertEqual(2, second.state.receiver.depth)
        self.assertEqual((0,), second.state.receiver.reserved_by_plane)
        self.assertEqual(
            (1, 2),
            tuple(
                transfer.flit.packet.message.transaction_id
                for transfer in second.state.receiver.captured
            ),
        )

    def test_tx_queue_full_returns_backpressure_without_mutation(self) -> None:
        state = self.path.initial_state()
        state = self.apply(state, ChiReqEnqueue(self.read(1))).state
        state = self.apply(state, ChiReqEnqueue(self.read(2))).state

        blocked = self.path.step(state, ChiReqEnqueue(self.read(3)))

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertIn("queue is full", blocked.blocked.reason)

    def test_receiver_drain_reopens_credit_and_delivery(self) -> None:
        path = ChiReqPointToPointSession(
            self.link,
            transmitter_capacity=2,
            receiver_capacities_by_plane=(1,),
        )
        state = path.initial_state()
        for transaction_id in (1, 2):
            transition = path.step(
                state, ChiReqEnqueue(self.read(transaction_id))
            )
            self.assertIsNone(transition.blocked)
            state = transition.state
        for _ in range(3):
            transition = path.step(state, ChiReqPathTick())
            self.assertIsNone(transition.fault)
            state = transition.state
        self.assertEqual(1, state.receiver.depth)
        self.assertEqual(1, state.transmitter.depth)

        stalled = path.step(state, ChiReqPathTick())
        self.assertIsNone(stalled.emissions[0].transfer)
        self.assertEqual((False,), stalled.emissions[0].grants_by_plane)

        drained = path.step(stalled.state, ChiReqDrain())
        self.assertIsNone(drained.blocked)
        grant = path.step(drained.state, ChiReqPathTick())
        self.assertEqual((True,), grant.emissions[0].grants_by_plane)
        self.assertIsNone(grant.emissions[0].transfer)
        delivered = path.step(grant.state, ChiReqPathTick())
        self.assertEqual(
            ChiReqTransferKind.PROTOCOL,
            delivered.emissions[0].transfer.kind,
        )
        self.assertEqual(0, delivered.state.transmitter.depth)
        self.assertEqual(1, delivered.state.receiver.depth)

    def test_deactivation_returns_unused_credit_before_stop(self) -> None:
        state = self.path.initial_state()
        state = self.apply(state, ChiReqPathTick()).state
        state = self.apply(state, ChiReqPathTick()).state
        self.assertEqual((1,), state.link.request.usable_credits_by_plane)

        deactivating = self.apply(state, ChiReqPathTick(active=False))
        observation = deactivating.emissions[0]
        self.assertEqual(ChiLinkActivationPhase.DEACTIVATE, observation.phase)
        self.assertEqual(
            ChiReqTransferKind.LINK_CREDIT_RETURN,
            observation.transfer.kind,
        )
        self.assertEqual(
            (0,), deactivating.state.link.request.usable_credits_by_plane
        )

        stopped = self.apply(
            deactivating.state, ChiReqPathTick(active=False)
        )
        self.assertEqual(ChiLinkActivationPhase.STOP, stopped.emissions[0].phase)
        self.assertTrue(self.path.is_quiescent(stopped.state))

    def test_request_enqueued_during_deactivation_reactivates_link(self) -> None:
        state = self.path.initial_state()
        state = self.apply(state, ChiReqPathTick()).state
        state = self.apply(state, ChiReqPathTick()).state
        state = self.apply(state, ChiReqPathTick(active=False)).state
        self.assertEqual(
            ChiLinkActivationPhase.DEACTIVATE, state.link.activation.phase
        )
        self.assertEqual((0,), state.link.request.usable_credits_by_plane)

        state = self.apply(state, ChiReqEnqueue(self.read(7))).state
        stopped = self.apply(state, ChiReqPathTick(active=False))
        self.assertEqual(ChiLinkActivationPhase.STOP, stopped.emissions[0].phase)
        activating = self.apply(
            stopped.state, ChiReqPathTick(active=False)
        )
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            activating.emissions[0].phase,
        )
        running = self.apply(
            activating.state, ChiReqPathTick(active=False)
        )
        delivered = self.apply(
            running.state, ChiReqPathTick(active=False)
        )
        self.assertEqual(
            ChiReqTransferKind.PROTOCOL,
            delivered.emissions[0].transfer.kind,
        )
        self.assertEqual(0, delivered.state.transmitter.depth)

    def test_captured_request_keeps_stopped_path_non_quiescent(self) -> None:
        state = self.path.initial_state()
        state = self.apply(state, ChiReqEnqueue(self.read(1))).state
        for _ in range(3):
            state = self.apply(state, ChiReqPathTick()).state
        state = self.apply(state, ChiReqPathTick(active=False)).state
        state = self.apply(state, ChiReqPathTick(active=False)).state

        self.assertEqual(1, state.receiver.depth)
        self.assertFalse(self.path.is_quiescent(state))
        state = self.apply(state, ChiReqDrain()).state
        self.assertTrue(self.path.is_quiescent(state))


if __name__ == "__main__":
    unittest.main()
