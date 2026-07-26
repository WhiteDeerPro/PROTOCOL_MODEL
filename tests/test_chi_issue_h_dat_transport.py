from __future__ import annotations

import unittest

from protocol_model.observation import AtomicFrame
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiCompDataMessage,
    ChiDatLCrdReturn,
    ChiIssueHDatProfile,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiDatChannelProfile,
    ChiDatChannelSignals,
    ChiDatTransferKind,
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiReqChannelSignals,
    ChiTransportLink,
    ChiTransportLinkProfile,
)


class ChiIssueHDatTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiTransportLinkProfile(
            request=None,
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=1,
                observation="home_to_rn.dat",
            ),
            clock="chi_clk",
            activation_observation="home_to_rn.active",
        )
        self.link = ChiTransportLink(
            "home_to_rn",
            ChiLinkEndpointRef("home", "txlink"),
            ChiLinkEndpointRef("rn_i", "rxlink"),
            self.profile,
        )
        self.session = self.link.open_session()

    @staticmethod
    def data(payload: int = 0xA5) -> ChiProtocolFlit:
        return ChiProtocolFlit(
            ChiNetworkPacket.data(
                ChiCompDataMessage(
                    transaction_id=3,
                    home_node_id=0x21,
                    data=payload,
                    data_id=0,
                ),
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
                "home_to_rn.active": ChiLinkActivationSignals(
                    request, acknowledge
                ),
                "home_to_rn.dat": ChiDatChannelSignals(
                    flit_valid=flit is not None,
                    flit=flit,
                    lcrdv=grant,
                ),
            },
        )

    def enter_run(self, *, grant: bool):
        state = self.session.initial_state()
        state = self.session.step(
            state, self.frame(0, ChiLinkActivationPhase.ACTIVATE)
        ).state
        transition = self.session.step(
            state, self.frame(1, ChiLinkActivationPhase.RUN, grant=grant)
        )
        self.assertIsNone(transition.fault)
        return transition.state

    def test_dat_credit_and_comp_data_transfer(self) -> None:
        state = self.enter_run(grant=True)
        self.assertEqual(1, state.data.usable_credits)

        sent = self.session.step(
            state,
            self.frame(2, ChiLinkActivationPhase.RUN, flit=self.data()),
        )

        self.assertIsNone(sent.fault)
        self.assertEqual(0, sent.state.data.usable_credits)
        self.assertEqual(ChiDatTransferKind.PROTOCOL, sent.emissions[0].kind)
        self.assertEqual(
            3,
            sent.emissions[0].flit.packet.message.semantic_key,
        )

    def test_same_frame_dat_grant_cannot_authorize_transfer(self) -> None:
        state = self.enter_run(grant=False)
        failed = self.session.step(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.RUN,
                flit=self.data(),
                grant=True,
            ),
        )
        self.assertIsNotNone(failed.fault)
        self.assertIs(state, failed.state)
        self.assertIn("frame start", failed.fault.reason)

    def test_dat_credit_return_precedes_stop(self) -> None:
        state = self.enter_run(grant=True)
        returned = self.session.step(
            state,
            self.frame(
                2,
                ChiLinkActivationPhase.DEACTIVATE,
                flit=ChiDatLCrdReturn(),
            ),
        )
        self.assertIsNone(returned.fault)
        self.assertEqual(0, returned.state.data.usable_credits)
        self.assertEqual(
            ChiDatTransferKind.LINK_CREDIT_RETURN,
            returned.emissions[0].kind,
        )
        stopped = self.session.step(
            returned.state, self.frame(3, ChiLinkActivationPhase.STOP)
        )
        self.assertIsNone(stopped.fault)

    def test_dat_fault_rolls_back_req_on_a_multi_channel_link(self) -> None:
        profile = ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                credit_capacities=(1,), observation="mixed.req"
            ),
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=1,
                observation="mixed.dat",
            ),
            clock="chi_clk",
            activation_observation="mixed.active",
        )
        link = ChiTransportLink(
            "mixed",
            ChiLinkEndpointRef("a", "tx"),
            ChiLinkEndpointRef("b", "rx"),
            profile,
        )
        session = link.open_session()

        def mixed_frame(tick, phase, *, req=None, dat=None, grant=False):
            active = {
                ChiLinkActivationPhase.ACTIVATE: (True, False),
                ChiLinkActivationPhase.RUN: (True, True),
            }[phase]
            return AtomicFrame(
                tick,
                "chi_clk",
                {
                    "mixed.active": ChiLinkActivationSignals(*active),
                    "mixed.req": ChiReqChannelSignals(
                        flit_valid=req is not None,
                        flit=req,
                        lcrdv_by_plane=(grant,),
                    ),
                    "mixed.dat": ChiDatChannelSignals(
                        flit_valid=dat is not None,
                        flit=dat,
                        lcrdv=grant,
                    ),
                },
            )

        state = session.initial_state()
        state = session.step(
            state,
            mixed_frame(0, ChiLinkActivationPhase.ACTIVATE),
        ).state
        state = session.step(
            state,
            mixed_frame(1, ChiLinkActivationPhase.RUN, grant=True),
        ).state
        read = ChiProtocolFlit(
            ChiNetworkPacket.request(
                ChiReadNoSnpMessage(3, 0x4000, size=3),
                source_id=0x07,
                target_id=0x21,
            )
        )
        invalid_data = self.data(1 << 128)

        failed = session.step(
            state,
            mixed_frame(
                2,
                ChiLinkActivationPhase.RUN,
                req=read,
                dat=invalid_data,
            ),
        )

        self.assertIsNotNone(failed.fault)
        self.assertIs(state, failed.state)
        self.assertEqual((), failed.emissions)


if __name__ == "__main__":
    unittest.main()
