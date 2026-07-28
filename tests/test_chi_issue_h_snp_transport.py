from __future__ import annotations

import unittest

from protocol_model.observation import AtomicFrame
from protocol_model.protocols.amba.chi.issue_h.representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiIssueHSnpProfile,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiSnpLCrdReturn,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiLinkEndpointRef,
    ChiSnpChannelProfile,
    ChiSnpChannelSignals,
    ChiSnpTransferKind,
    ChiTransportLink,
    ChiTransportLinkProfile,
)


class ChiIssueHSnpTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiTransportLinkProfile(
            request=None,
            response=None,
            data=None,
            snoop=ChiSnpChannelProfile(
                representation=ChiIssueHSnpProfile(
                    node_id_width=7,
                    snoop_address_width=44,
                ),
                credit_capacity=1,
                observation="home_to_rn.snp",
            ),
            clock="chi_clk",
            activation_observation="home_to_rn.active",
        )
        self.session = ChiTransportLink(
            "home_to_rn",
            ChiLinkEndpointRef("home", "txsnp"),
            ChiLinkEndpointRef("rn_f", "rxsnp"),
            self.profile,
        ).open_session()

    @staticmethod
    def snoop_message(
        transaction_id: int = 3,
    ) -> ChiSnpSharedMessage:
        return ChiSnpSharedMessage(
            transaction_id=transaction_id,
            address=0x4000,
            pas=0,
            return_to_source=True,
        )

    @classmethod
    def snoop_flit(cls, transaction_id: int = 3) -> ChiProtocolFlit:
        return ChiProtocolFlit(
            ChiNetworkPacket.snoop(
                cls.snoop_message(transaction_id),
                source_id=0x21,
                target_id=0x07,
            )
        )

    def frame(
        self,
        tick: int,
        phase: ChiLinkActivationPhase,
        *,
        flit=None,
        lcrdv: bool = False,
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
                "home_to_rn.active": ChiLinkActivationSignals(
                    request,
                    acknowledge,
                ),
                "home_to_rn.snp": ChiSnpChannelSignals(
                    flit_valid=flit is not None,
                    flit=flit,
                    lcrdv=lcrdv,
                ),
            },
        )

    def apply(self, state, frame):
        transition = self.session.step(state, frame)
        self.assertIsNone(transition.fault)
        return transition

    def running_with_credit(self):
        state = self.session.initial_state()
        state = self.apply(
            state,
            self.frame(0, ChiLinkActivationPhase.ACTIVATE),
        ).state
        state = self.apply(
            state,
            self.frame(1, ChiLinkActivationPhase.RUN, lcrdv=True),
        ).state
        self.assertEqual(1, state.snoop.usable_credits)
        return state

    def test_snp_message_has_no_target_field_and_profile_checks_fields(self) -> None:
        snoop = self.snoop_message()

        self.assertFalse(hasattr(snoop, "target_id"))
        self.assertEqual((), self.profile.snoop.representation.explain(snoop))
        classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(snoop)
        self.assertIs(ChiChannelKind.SNP, classification.channel)
        self.assertTrue(classification.is_message)

        unaligned = ChiSnpSharedMessage(
            transaction_id=4,
            address=0x4001,
        )
        self.assertIn(
            "8-byte aligned",
            self.profile.snoop.representation.explain(unaligned)[0],
        )

    def test_snp_protocol_flit_consumes_a_prior_credit(self) -> None:
        state = self.running_with_credit()

        sent = self.apply(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.RUN,
                flit=self.snoop_flit(),
            ),
        )

        self.assertEqual(0, sent.state.snoop.usable_credits)
        self.assertEqual(1, len(sent.emissions))
        self.assertEqual(
            ChiSnpTransferKind.PROTOCOL,
            sent.emissions[0].kind,
        )
        self.assertIsInstance(sent.emissions[0].flit, ChiProtocolFlit)
        self.assertEqual(
            0x07,
            sent.emissions[0].flit.packet.target_id,
        )

    def test_snp_unique_reuses_the_typed_snp_transport(self) -> None:
        state = self.running_with_credit()
        message = ChiSnpUniqueMessage(
            transaction_id=4,
            address=0x4000,
            return_to_source=False,
        )
        flit = ChiProtocolFlit(
            ChiNetworkPacket.snoop(
                message,
                source_id=0x21,
                target_id=0x07,
            )
        )

        sent = self.apply(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.RUN,
                flit=flit,
            ),
        )

        self.assertIs(
            message,
            sent.emissions[0].flit.packet.message,
        )
        self.assertEqual(0, sent.state.snoop.usable_credits)

    def test_same_frame_grant_does_not_authorize_snp_flit(self) -> None:
        state = self.session.initial_state()
        state = self.apply(
            state,
            self.frame(0, ChiLinkActivationPhase.ACTIVATE),
        ).state

        failed = self.session.step(
            state,
            self.frame(
                1,
                ChiLinkActivationPhase.RUN,
                flit=self.snoop_flit(),
                lcrdv=True,
            ),
        )

        self.assertIsNotNone(failed.fault)
        self.assertIn("frame start", failed.fault.reason)

    def test_unused_snp_credit_returns_before_stop(self) -> None:
        state = self.running_with_credit()

        returning = self.apply(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.DEACTIVATE,
                flit=ChiSnpLCrdReturn(),
            ),
        )
        self.assertEqual(
            ChiSnpTransferKind.LINK_CREDIT_RETURN,
            returning.emissions[0].kind,
        )
        stopped = self.apply(
            returning.state,
            self.frame(3, ChiLinkActivationPhase.STOP),
        )
        self.assertTrue(self.session.is_quiescent(stopped.state))


if __name__ == "__main__":
    unittest.main()
