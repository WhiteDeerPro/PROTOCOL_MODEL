from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpRetryLedger,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_REQUEST_RETRY_HOME_CAPABILITIES,
    CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
    ChiBehaviorFacet,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiRetryHomeNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_REQUEST_RETRY,
    ChiAdvanceReadNetwork,
    ChiCancelRead,
    ChiReadNoSnpRetrySystemSession,
    ChiReadNoSnpSystemEventKind,
    ChiSubmitRead,
    ChiFeatureContract,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.system import SystemProtocolBuilder, VirtualDutPortRef
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHRetrySystemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(0x07, 0x21, 128, 2)
        self.ledger = ChiReadNoSnpRetryLedger("rn.retry", self.profile)
        self.home = ChiRetryHomeNode(
            "home",
            self.profile,
            lambda request: 0xD000_0000 | request.address,
            request_capacity=1,
            retry_policy=lambda request, state: 4,
        )
        self.system = self._build_system().elaborate()
        self.requester_binding, self.home_binding = self._bindings()

    @staticmethod
    def port(name: str, direction: TransportDirection) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    def _build_system(self):
        builder = SystemProtocolBuilder("chi_retry_direct")
        builder.add_dut(
            VirtualDut(
                "rn",
                {
                    "tx_req": self.port("tx_req", TransportDirection.TRANSMIT),
                    "rx_return": self.port(
                        "rx_return", TransportDirection.RECEIVE
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "home",
                {
                    "rx_req": self.port("rx_req", TransportDirection.RECEIVE),
                    "tx_return": self.port(
                        "tx_return", TransportDirection.TRANSMIT
                    ),
                },
            )
        )
        req = ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                ChiIssueHReqProfile(), (1,), "retry.req"
            ),
            data=None,
            response=None,
            clock="chi_clk",
            activation_observation="retry.req.active",
        )
        returned = ChiTransportLinkProfile(
            request=None,
            data=ChiDatChannelProfile(
                ChiIssueHDatProfile(data_width=128), 1, "retry.dat"
            ),
            response=ChiRspChannelProfile(
                ChiIssueHRspProfile(), 1, "retry.rsp"
            ),
            clock="chi_clk",
            activation_observation="retry.return.active",
        )
        for name, transmitter, receiver, profile in (
            (
                "request",
                VirtualDutPortRef("rn", "tx_req"),
                VirtualDutPortRef("home", "rx_req"),
                req,
            ),
            (
                "return",
                VirtualDutPortRef("home", "tx_return"),
                VirtualDutPortRef("rn", "rx_return"),
                returned,
            ),
        ):
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=profile,
            )
        return builder.build()

    def _bindings(self):
        duts = self.system.spec.virtual_duts
        item = ChiParticipantPortBinding
        requester = ChiParticipantBinding(
            "rn.retry",
            duts["rn"],
            self.ledger,
            (
                item(duts["rn"].port("tx_req"), frozenset((ChiChannelKind.REQ,))),
                item(
                    duts["rn"].port("rx_return"),
                    frozenset(
                        (ChiChannelKind.RSP, ChiChannelKind.DAT)
                    ),
                ),
            ),
            frozenset((self.profile.requester_node_id,)),
        )
        home = ChiParticipantBinding(
            "home",
            duts["home"],
            self.home,
            (
                item(duts["home"].port("rx_req"), frozenset((ChiChannelKind.REQ,))),
                item(
                    duts["home"].port("tx_return"),
                    frozenset(
                        (ChiChannelKind.RSP, ChiChannelKind.DAT)
                    ),
                ),
            ),
            frozenset((self.profile.home_node_id,)),
        )
        return requester, home

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

    def test_retry_flow_closes_without_manual_transport_actions(self) -> None:
        contract = ChiFeatureContract(
            {
                "requester": self.requester_binding.name,
                "home": self.home_binding.name,
            },
            frozenset((CHI_FEATURE_REQUEST_RETRY,)),
        )
        resolved = resolve_chi_system(
            self.system,
            facets=(
                ChiBehaviorFacet.from_binding(
                    self.requester_binding,
                    ChiFacetKind.TRANSACTION,
                ),
                ChiBehaviorFacet.from_binding(
                    self.home_binding,
                    ChiFacetKind.TRANSACTION,
                ),
            ),
            feature_contract=contract,
            participant_capabilities=(
                ChiParticipantCapability(
                    self.requester_binding.name,
                    CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    self.home_binding.name,
                    CHI_REQUEST_RETRY_HOME_CAPABILITIES,
                ),
            ),
        )
        self.assertTrue(resolved.is_closed)
        session = ChiReadNoSnpRetrySystemSession.from_resolved(resolved)
        self.assertIs(session.network, resolved.network)
        self.assertEqual(
            frozenset((ChiChannelKind.RSP, ChiChannelKind.DAT)),
            session.network.paths["return"].channels,
        )
        issued = session.step(
            session.initial_state(),
            ChiSubmitRead(self.requester_binding.name, self.request()),
        )
        self.assertIsNone(issued.fault)
        self.assertIsNone(issued.blocked)

        run = session.run_until_quiescent(issued.state, max_steps=512)

        self.assertTrue(run.ok)
        self.assertIsNone(run.blocked)
        self.assertTrue(session.is_quiescent(run.final_state))
        self.assertEqual(1, run.final_state.home.retry_ack_count)
        self.assertEqual(1, run.final_state.home.grant_count)
        self.assertEqual(1, run.final_state.home.retried_accept_count)
        self.assertEqual(1, len(run.final_state.requester.completed))
        self.assertEqual(
            0xD000_4020, run.final_state.requester.completed[0].data
        )
        kinds = tuple(event.kind for event in run.emissions)
        self.assertEqual(1, kinds.count(ChiReadNoSnpSystemEventKind.HOME_RETRY_ACK))
        self.assertEqual(
            1, kinds.count(ChiReadNoSnpSystemEventKind.HOME_PCREDIT_GRANT)
        )
        self.assertEqual(2, kinds.count(ChiReadNoSnpSystemEventKind.REQUESTER_RSP))
        self.assertEqual(1, kinds.count(ChiReadNoSnpSystemEventKind.RETRY))
        self.assertEqual(1, kinds.count(ChiReadNoSnpSystemEventKind.COMPLETE))

    def test_cancel_returns_pcredit_over_req_route(self) -> None:
        session = ChiReadNoSnpRetrySystemSession(
            self.system,
            requester=self.requester_binding,
            home=self.home_binding,
        )
        issued = session.step(
            session.initial_state(),
            ChiSubmitRead(self.requester_binding.name, self.request()),
        )
        self.assertIsNone(issued.fault)
        state = issued.state
        for _ in range(256):
            if session.requester.retryable_keys(state.requester):
                break
            advanced = session.step(state, ChiAdvanceReadNetwork())
            self.assertIsNone(advanced.fault)
            self.assertIsNone(advanced.blocked)
            state = advanced.state
        else:
            self.fail("RetryAck and PCrdGrant did not reach the Requester")

        canceled = session.step(
            state,
            ChiCancelRead(
                self.requester_binding.name,
                self.request().transaction_id,
            ),
        )

        self.assertIsNone(canceled.fault)
        self.assertIsNone(canceled.blocked)
        self.assertEqual(
            ChiReadNoSnpSystemEventKind.REQUESTER_PCREDIT_RETURN,
            canceled.emissions[0].kind,
        )
        self.assertEqual("request", canceled.emissions[0].connection)

        run = session.run_until_quiescent(canceled.state, max_steps=256)

        self.assertTrue(run.ok)
        self.assertTrue(session.is_quiescent(run.final_state))
        self.assertEqual(1, run.final_state.home.returned_credit_count)
        self.assertEqual(0, run.final_state.home.retried_accept_count)
        self.assertEqual((), run.final_state.requester.completed)
        self.assertIn(
            ChiReadNoSnpSystemEventKind.HOME_PCREDIT_RETURN,
            tuple(event.kind for event in run.emissions),
        )


if __name__ == "__main__":
    unittest.main()
