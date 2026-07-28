from __future__ import annotations

import unittest

from protocol_model.observation import AtomicFrame
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiIssueHReqProfile,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiReadNoSnpMessage,
    ChiReqLCrdReturn,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiReqChannelSignals,
    ChiReqTransferKind,
    ChiTransportLink,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import ConstraintScope


class ChiIssueHReqTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                representation=ChiIssueHReqProfile(
                    node_id_width=7,
                    request_address_width=44,
                ),
                credit_capacities=(1,),
                observation="outbound.req",
            ),
            clock="chi_clk",
            activation_observation="outbound.link",
        )
        self.link = ChiTransportLink(
            "rn_to_icn",
            ChiLinkEndpointRef("rn_i", "chi_tx"),
            ChiLinkEndpointRef("icn", "rn_rx"),
            self.profile,
        )
        self.session = self.link.open_session()

    @staticmethod
    def read(transaction_id: int = 3) -> ChiProtocolFlit:
        return ChiProtocolFlit(
            ChiNetworkPacket.request(
                ChiReadNoSnpMessage(
                    transaction_id=transaction_id,
                    address=0x4000,
                    size=6,
                    memory_attributes=0,
                ),
                source_id=0x07,
                target_id=0x21,
            )
        )

    def frame(
        self,
        tick: int,
        phase: ChiLinkActivationPhase,
        *,
        flit=None,
        grant: bool = False,
    ) -> AtomicFrame:
        request, acknowledge = {
            ChiLinkActivationPhase.STOP: (False, False),
            ChiLinkActivationPhase.ACTIVATE: (True, False),
            ChiLinkActivationPhase.RUN: (True, True),
            ChiLinkActivationPhase.DEACTIVATE: (False, True),
        }[phase]
        return AtomicFrame(
            tick,
            "chi_clk",
            {
                "outbound.link": ChiLinkActivationSignals(
                    request, acknowledge
                ),
                "outbound.req": ChiReqChannelSignals(
                    flit_valid=flit is not None,
                    flit=flit,
                    lcrdv_by_plane=(grant,),
                ),
            },
        )

    def enter_run(self, *, grant: bool = False):
        state = self.session.initial_state()
        activate = self.session.step(
            state, self.frame(0, ChiLinkActivationPhase.ACTIVATE)
        )
        self.assertIsNone(activate.fault)
        running = self.session.step(
            activate.state,
            self.frame(1, ChiLinkActivationPhase.RUN, grant=grant),
        )
        self.assertIsNone(running.fault)
        return running.state

    def test_credit_granted_with_run_is_usable_only_next_frame(self) -> None:
        state = self.enter_run(grant=True)

        self.assertEqual((1,), state.request.usable_credits_by_plane)
        transfer = self.session.step(
            state, self.frame(2, ChiLinkActivationPhase.RUN, flit=self.read())
        )

        self.assertIsNone(transfer.fault)
        self.assertEqual(
            (0,), transfer.state.request.usable_credits_by_plane
        )
        self.assertEqual(1, len(transfer.emissions))
        self.assertEqual(ChiReqTransferKind.PROTOCOL, transfer.emissions[0].kind)
        self.assertEqual(
            3,
            transfer.emissions[0].flit.packet.message.semantic_key,
        )

    def test_synchronous_boundary_grants_credit_on_run_entry(self) -> None:
        initial = self.session.initial_state()
        activating = self.session.step(
            initial, self.frame(0, ChiLinkActivationPhase.ACTIVATE)
        )
        self.assertIsNone(activating.fault)

        invalid_grant = self.session.step(
            activating.state,
            self.frame(1, ChiLinkActivationPhase.ACTIVATE, grant=True),
        )
        self.assertIsNotNone(invalid_grant.fault)
        self.assertIn("grants credits in RUN", invalid_grant.fault.reason)

        running = self.session.step(
            activating.state,
            self.frame(1, ChiLinkActivationPhase.RUN, grant=True),
        )
        self.assertIsNone(running.fault)
        transfer = self.session.step(
            running.state,
            self.frame(2, ChiLinkActivationPhase.RUN, flit=self.read()),
        )
        self.assertIsNone(transfer.fault)
        self.assertEqual(
            (0,), transfer.state.request.usable_credits_by_plane
        )

    def test_same_frame_credit_cannot_authorize_a_flit(self) -> None:
        state = self.enter_run()
        transition = self.session.step(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.RUN,
                flit=self.read(),
                grant=True,
            ),
        )

        self.assertIsNotNone(transition.fault)
        self.assertEqual(ConstraintScope.TRANSPORT, transition.fault.scope)
        self.assertIn("frame start", transition.fault.reason)
        self.assertIs(state, transition.state)
        self.assertEqual((), transition.emissions)

    def test_send_and_replacement_credit_can_share_a_frame(self) -> None:
        state = self.enter_run(grant=True)
        transition = self.session.step(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.RUN,
                flit=self.read(),
                grant=True,
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual(
            (1,), transition.state.request.usable_credits_by_plane
        )
        self.assertEqual(1, len(transition.emissions))

    def test_deactivation_returns_unused_credit_before_stop(self) -> None:
        state = self.enter_run(grant=True)
        deactivating = self.session.step(
            state, self.frame(2, ChiLinkActivationPhase.DEACTIVATE)
        )
        self.assertIsNone(deactivating.fault)

        early_stop = self.session.step(
            deactivating.state, self.frame(3, ChiLinkActivationPhase.STOP)
        )
        self.assertIsNotNone(early_stop.fault)
        self.assertIn("all credits", early_stop.fault.reason)

        returned = self.session.step(
            deactivating.state,
            self.frame(
                3,
                ChiLinkActivationPhase.DEACTIVATE,
                flit=ChiReqLCrdReturn(),
            ),
        )
        self.assertIsNone(returned.fault)
        self.assertEqual(
            (0,), returned.state.request.usable_credits_by_plane
        )
        self.assertEqual(
            ChiReqTransferKind.LINK_CREDIT_RETURN,
            returned.emissions[0].kind,
        )

        stopped = self.session.step(
            returned.state, self.frame(4, ChiLinkActivationPhase.STOP)
        )
        self.assertIsNone(stopped.fault)
        self.assertTrue(self.session.is_quiescent(stopped.state))

    def test_deactivate_entry_credit_race_can_feed_a_late_protocol_flit(self) -> None:
        state = self.enter_run()
        entering = self.session.step(
            state,
            self.frame(2, ChiLinkActivationPhase.DEACTIVATE, grant=True),
        )

        self.assertIsNone(entering.fault)
        self.assertEqual(
            (1,), entering.state.request.usable_credits_by_plane
        )
        late = self.session.step(
            entering.state,
            self.frame(
                3,
                ChiLinkActivationPhase.DEACTIVATE,
                flit=self.read(transaction_id=4),
            ),
        )
        self.assertIsNone(late.fault)
        self.assertEqual((0,), late.state.request.usable_credits_by_plane)
        self.assertEqual(ChiReqTransferKind.PROTOCOL, late.emissions[0].kind)

    def test_activation_order_and_credit_capacity_are_checked(self) -> None:
        initial = self.session.initial_state()
        skipped = self.session.step(
            initial, self.frame(0, ChiLinkActivationPhase.RUN)
        )
        self.assertIsNotNone(skipped.fault)
        self.assertIn("illegal activation transition", skipped.fault.reason)

        state = self.enter_run(grant=True)
        overflow = self.session.step(
            state, self.frame(2, ChiLinkActivationPhase.RUN, grant=True)
        )
        self.assertIsNotNone(overflow.fault)
        self.assertIn("configured capacity", overflow.fault.reason)

    def test_channel_fault_rolls_back_link_wide_activation(self) -> None:
        initial = self.session.initial_state()
        activating = self.session.step(
            initial, self.frame(0, ChiLinkActivationPhase.ACTIVATE)
        )
        self.assertIsNone(activating.fault)

        failed = self.session.step(
            activating.state,
            self.frame(
                1,
                ChiLinkActivationPhase.RUN,
                flit=self.read(),
                grant=True,
            ),
        )
        self.assertIsNotNone(failed.fault)
        self.assertIs(activating.state, failed.state)
        self.assertEqual(
            ChiLinkActivationPhase.ACTIVATE,
            failed.state.activation.phase,
        )
        self.assertEqual((0,), failed.state.request.usable_credits_by_plane)

    def test_read_no_snp_uses_profile_dependent_widths(self) -> None:
        representation = self.profile.request.representation
        valid = self.read()
        self.assertEqual((), valid.packet.explain_profile(representation))

        bad_target = ChiNetworkPacket.request(
            ChiReadNoSnpMessage(transaction_id=1, address=0x4000),
            source_id=0x07,
            target_id=0x80,
        )
        reasons = bad_target.explain_profile(representation)
        self.assertTrue(any("TgtID" in reason for reason in reasons))

        reserved_pas = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0,
            pas=6,
        )
        self.assertTrue(
            any("PAS" in reason for reason in representation.explain(reserved_pas))
        )

        invalid_retry_credit = ChiReadNoSnpMessage(
            transaction_id=3,
            address=0,
            allow_retry=True,
            protocol_credit_type=1,
        )
        self.assertTrue(
            any(
                "PCrdType" in reason
                for reason in representation.explain(invalid_retry_credit)
            )
        )

        with self.assertRaisesRegex(ValueError, "reserved"):
            ChiReadNoSnpMessage(transaction_id=3, address=0, size=7)


if __name__ == "__main__":
    unittest.main()
