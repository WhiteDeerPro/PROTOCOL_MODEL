from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiIssueHDatProfile,
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.transport.data_path import (
    ChiDatDrain,
    ChiDatEnqueue,
    ChiDatPathTick,
    ChiDatPointToPointSession,
)
from protocol_model.protocols.amba.chi.issue_h.transport.link import (
    ChiDatChannelProfile,
    ChiDatTransferKind,
    ChiLinkActivationPhase,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiTransportLink,
    ChiTransportLinkProfile,
)


class ChiIssueHDatPointToPointPathTest(unittest.TestCase):
    def make_path(
        self,
        *,
        tx_capacity: int = 2,
        rx_capacity: int = 2,
        credit_capacity: int = 1,
    ) -> ChiDatPointToPointSession:
        profile = ChiTransportLinkProfile(
            request=None,
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=credit_capacity,
                observation="home_to_rn.dat",
            ),
            clock="chi_clk",
            activation_observation="home_to_rn.active",
        )
        link = ChiTransportLink(
            "home_to_rn",
            ChiLinkEndpointRef("home", "txlink"),
            ChiLinkEndpointRef("rn_i", "rxlink"),
            profile,
        )
        return ChiDatPointToPointSession(
            link,
            transmitter_capacity=tx_capacity,
            receiver_capacity=rx_capacity,
        )

    @staticmethod
    def data(transaction_id: int) -> ChiNetworkPacket:
        return ChiNetworkPacket.data(
            ChiCompDataMessage(
                transaction_id=transaction_id,
                home_node_id=0x21,
                data=0xA500 + transaction_id,
                data_id=0,
            ),
            source_id=0x21,
            target_id=0x07,
        )

    def apply(self, path, state, action):
        transition = path.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_grant_is_next_frame_only_and_can_replace_old_credit(self) -> None:
        path = self.make_path()
        state = path.initial_state()
        state = self.apply(path, state, ChiDatEnqueue(self.data(1))).state
        state = self.apply(path, state, ChiDatEnqueue(self.data(2))).state

        activating = self.apply(path, state, ChiDatPathTick())
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            activating.emissions[0].phase,
        )
        running = self.apply(path, activating.state, ChiDatPathTick())
        self.assertTrue(running.emissions[0].grant)
        self.assertIsNone(running.emissions[0].transfer)
        self.assertEqual(2, running.state.transmitter.depth)

        first = self.apply(path, running.state, ChiDatPathTick())
        self.assertTrue(first.emissions[0].grant)
        self.assertEqual(
            ChiDatTransferKind.PROTOCOL,
            first.emissions[0].transfer.kind,
        )
        self.assertEqual(1, first.state.link.data.usable_credits)
        self.assertEqual(1, first.state.receiver.reserved_credits)

        second = self.apply(path, first.state, ChiDatPathTick())
        self.assertFalse(second.emissions[0].grant)
        self.assertEqual(0, second.state.transmitter.depth)
        self.assertEqual(2, second.state.receiver.depth)
        self.assertEqual(0, second.state.link.data.usable_credits)

    def test_full_transmitter_fifo_returns_backpressure(self) -> None:
        path = self.make_path(tx_capacity=1)
        state = path.initial_state()
        state = self.apply(path, state, ChiDatEnqueue(self.data(1))).state

        blocked = path.step(state, ChiDatEnqueue(self.data(2)))

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertIn("queue is full", blocked.blocked.reason)

    def test_full_capture_stalls_until_drain_reopens_credit(self) -> None:
        path = self.make_path(rx_capacity=1)
        state = path.initial_state()
        for transaction_id in (1, 2):
            state = self.apply(
                path, state, ChiDatEnqueue(self.data(transaction_id))
            ).state
        for _ in range(3):
            state = self.apply(path, state, ChiDatPathTick()).state
        self.assertEqual(1, state.transmitter.depth)
        self.assertEqual(1, state.receiver.depth)

        stalled = self.apply(path, state, ChiDatPathTick())
        self.assertFalse(stalled.emissions[0].grant)
        self.assertIsNone(stalled.emissions[0].transfer)

        drained = self.apply(path, stalled.state, ChiDatDrain())
        granted = self.apply(path, drained.state, ChiDatPathTick())
        self.assertTrue(granted.emissions[0].grant)
        self.assertIsNone(granted.emissions[0].transfer)
        delivered = self.apply(path, granted.state, ChiDatPathTick())
        self.assertEqual(
            ChiDatTransferKind.PROTOCOL,
            delivered.emissions[0].transfer.kind,
        )
        self.assertEqual(0, delivered.state.transmitter.depth)

    def test_deactivation_returns_unused_dat_credit_before_stop(self) -> None:
        path = self.make_path()
        state = path.initial_state()
        state = self.apply(path, state, ChiDatPathTick()).state
        state = self.apply(path, state, ChiDatPathTick()).state
        self.assertEqual(1, state.link.data.usable_credits)

        deactivating = self.apply(
            path, state, ChiDatPathTick(active=False)
        )
        self.assertEqual(
            ChiLinkActivationPhase.DEACTIVATE,
            deactivating.emissions[0].phase,
        )
        self.assertEqual(
            ChiDatTransferKind.LINK_CREDIT_RETURN,
            deactivating.emissions[0].transfer.kind,
        )
        self.assertEqual(0, deactivating.state.link.data.usable_credits)

        stopped = self.apply(
            path, deactivating.state, ChiDatPathTick(active=False)
        )
        self.assertEqual(
            ChiLinkActivationPhase.STOP,
            stopped.emissions[0].phase,
        )
        self.assertTrue(path.is_quiescent(stopped.state))

    def test_path_rejects_any_non_dat_only_profile(self) -> None:
        endpoint_a = ChiLinkEndpointRef("a", "tx")
        endpoint_b = ChiLinkEndpointRef("b", "rx")
        req_only = ChiTransportLink("req", endpoint_a, endpoint_b)
        with self.assertRaisesRegex(ValueError, "DAT-only"):
            ChiDatPointToPointSession(req_only)

        mixed = ChiTransportLink(
            "mixed",
            endpoint_a,
            endpoint_b,
            ChiTransportLinkProfile(
                request=ChiReqChannelProfile(),
                data=ChiDatChannelProfile(),
            ),
        )
        with self.assertRaisesRegex(ValueError, "DAT-only"):
            ChiDatPointToPointSession(mixed)

    def test_captured_data_keeps_stopped_path_non_quiescent(self) -> None:
        path = self.make_path(rx_capacity=1)
        state = path.initial_state()
        state = self.apply(path, state, ChiDatEnqueue(self.data(1))).state
        for _ in range(3):
            state = self.apply(path, state, ChiDatPathTick()).state
        state = self.apply(
            path, state, ChiDatPathTick(active=False)
        ).state
        state = self.apply(
            path, state, ChiDatPathTick(active=False)
        ).state

        self.assertEqual(1, state.receiver.depth)
        self.assertFalse(path.is_quiescent(state))
        state = self.apply(path, state, ChiDatDrain()).state
        self.assertTrue(path.is_quiescent(state))


if __name__ == "__main__":
    unittest.main()
