from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_READ_NO_SNP_HOME_CAPABILITIES,
    CHI_READ_NO_SNP_NDERR_HOME_CAPABILITIES,
    CHI_READ_NO_SNP_NDERR_REQUESTER_CAPABILITIES,
    CHI_READ_NO_SNP_REQUESTER_CAPABILITIES,
    ChiAddressHomeNode,
    ChiBehaviorFacet,
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiNetworkPacket,
    ChiPCrdReturnMessage,
    ChiReadNoSnpMessage,
    ChiRespErr,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_READ_NO_SNP,
    CHI_FEATURE_READ_NO_SNP_NDERR,
    ChiNetworkCaptureToRouter,
    ChiNetworkDrain,
    ChiNetworkEnqueue,
    ChiNetworkEventKind,
    ChiNetworkRouterToConnection,
    ChiNetworkTick,
    ChiCoherenceAuthorityContract,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemSession,
    ChiSubmitRead,
    ChiTransportNetworkSession,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.system import (
    AddressClaim,
    AddressWindow,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)
from protocol_model.virtual_dut.address import AddressSpace, MemoryRegion


class ChiIssueHFreeTopologyNetworkTest(unittest.TestCase):
    HOME_ADDRESS_CLAIM = "home.direct_window"

    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=2,
        )
        self.requester = ChiReadNoSnpDirectLedger(
            "rn_i.reads", self.profile
        )
        self.home = ChiDirectHomeNode(
            "home",
            self.profile,
            lambda request: 0xD000_0000 | request.address,
            request_capacity=1,
        )
        self.router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_rn", "from_home"),
            egress_ports=("to_rn", "to_home"),
            routes=(
                ChiExactNodeRoute(
                    self.profile.home_node_id,
                    "to_home",
                    frozenset((ChiChannelKind.REQ,)),
                ),
                ChiExactNodeRoute(
                    self.profile.requester_node_id,
                    "to_rn",
                    frozenset((ChiChannelKind.DAT,)),
                ),
            ),
            queue_capacity=1,
        )
        self.system = self.build_system().elaborate()
        self.network = ChiTransportNetworkSession(
            self.system, routers={"xp0": self.router}
        )

    @staticmethod
    def transport_port(name: str, direction: TransportDirection):
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    @staticmethod
    def req_profile(name: str) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=ChiReqChannelProfile(
                representation=ChiIssueHReqProfile(),
                credit_capacities=(1,),
                observation=f"{name}.req",
            ),
            data=None,
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    @staticmethod
    def dat_profile(name: str) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=None,
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=1,
                observation=f"{name}.dat",
            ),
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    def build_system(self):
        builder = SystemProtocolBuilder("chi_free_topology")
        builder.add_dut(
            VirtualDut(
                "rn_i",
                {
                    "tx_req": self.transport_port(
                        "tx_req", TransportDirection.TRANSMIT
                    ),
                    "rx_dat": self.transport_port(
                        "rx_dat", TransportDirection.RECEIVE
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "xp0",
                {
                    "from_rn": self.transport_port(
                        "from_rn", TransportDirection.RECEIVE
                    ),
                    "to_home": self.transport_port(
                        "to_home", TransportDirection.TRANSMIT
                    ),
                    "from_home": self.transport_port(
                        "from_home", TransportDirection.RECEIVE
                    ),
                    "to_rn": self.transport_port(
                        "to_rn", TransportDirection.TRANSMIT
                    ),
                },
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
            )
        )
        builder.add_dut(
            VirtualDut(
                "home",
                {
                    "rx_req": self.transport_port(
                        "rx_req", TransportDirection.RECEIVE
                    ),
                    "tx_dat": self.transport_port(
                        "tx_dat", TransportDirection.TRANSMIT
                    ),
                },
            )
        )
        for name, transmitter, receiver, profile in (
            (
                "rn_to_xp",
                VirtualDutPortRef("rn_i", "tx_req"),
                VirtualDutPortRef("xp0", "from_rn"),
                self.req_profile("rn_to_xp"),
            ),
            (
                "xp_to_home",
                VirtualDutPortRef("xp0", "to_home"),
                VirtualDutPortRef("home", "rx_req"),
                self.req_profile("xp_to_home"),
            ),
            (
                "home_to_xp",
                VirtualDutPortRef("home", "tx_dat"),
                VirtualDutPortRef("xp0", "from_home"),
                self.dat_profile("home_to_xp"),
            ),
            (
                "xp_to_rn",
                VirtualDutPortRef("xp0", "to_rn"),
                VirtualDutPortRef("rn_i", "rx_dat"),
                self.dat_profile("xp_to_rn"),
            ),
        ):
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=profile,
            )
        builder.add_address_claim(
            AddressClaim(
                self.HOME_ADDRESS_CLAIM,
                VirtualDutPortRef("home", "rx_req"),
                AddressWindow(0, 0x1_0000),
            )
        )
        return builder.build()

    def build_direct_request_system(self):
        builder = SystemProtocolBuilder("chi_direct_topology")
        builder.add_dut(
            VirtualDut(
                "direct_rn",
                {
                    "tx_req": self.transport_port(
                        "tx_req", TransportDirection.TRANSMIT
                    )
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "direct_home",
                {
                    "rx_req": self.transport_port(
                        "rx_req", TransportDirection.RECEIVE
                    )
                },
            )
        )
        builder.connect_transport(
            "direct_req",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("direct_rn", "tx_req"),
            VirtualDutPortRef("direct_home", "rx_req"),
            profile=self.req_profile("direct_req"),
        )
        return builder.build()

    def participant_bindings(self):
        """Bind participant behaviors to ports without naming topology hops."""

        duts = self.system.spec.virtual_duts
        port = ChiParticipantPortBinding
        requester = ChiParticipantBinding(
            "rn_i.reads",
            duts["rn_i"],
            self.requester,
            (
                port(
                    duts["rn_i"].port("tx_req"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
                port(
                    duts["rn_i"].port("rx_dat"),
                    frozenset((ChiChannelKind.DAT,)),
                ),
            ),
            frozenset((self.profile.requester_node_id,)),
        )
        home = ChiParticipantBinding(
            "home",
            duts["home"],
            self.home,
            (
                port(
                    duts["home"].port("rx_req"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
                port(
                    duts["home"].port("tx_dat"),
                    frozenset((ChiChannelKind.DAT,)),
                ),
            ),
            frozenset((self.profile.home_node_id,)),
        )
        router = ChiParticipantBinding(
            "xp0.fabric",
            duts["xp0"],
            self.router,
            tuple(
                port(duts["xp0"].port(name), frozenset((channel,)))
                for name, channel in (
                    ("from_rn", ChiChannelKind.REQ),
                    ("to_home", ChiChannelKind.REQ),
                    ("from_home", ChiChannelKind.DAT),
                    ("to_rn", ChiChannelKind.DAT),
                )
            ),
        )
        return requester, home, router

    @staticmethod
    def request(transaction_id: int = 3) -> ChiReadNoSnpMessage:
        return ChiReadNoSnpMessage(
            transaction_id=transaction_id,
            address=0x4020 + 0x10 * (transaction_id - 3),
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

    def tick(self, state, connection: str, count: int = 1, active=True):
        for _ in range(count):
            state = self.apply(
                self.network,
                state,
                ChiNetworkTick(connection, active),
            ).state
        return state

    def activate_all(self, state):
        for _ in range(3):
            for connection in self.system.transport_plan.hops_by_name:
                state = self.tick(state, connection)
        return state

    def test_read_uses_one_session_over_a_caller_defined_topology(self) -> None:
        request = self.request()
        ledger_state = self.requester.initial_state()
        home_state = self.home.initial_state()
        network_state = self.network.initial_state()

        ledger_issue = self.apply(
            self.requester,
            ledger_state,
            ChiReadNoSnpIssue(request),
        )
        network_issue = self.apply(
            self.network,
            network_state,
            ChiNetworkEnqueue(
                "rn_to_xp",
                ChiNetworkPacket.request(
                    request, source_id=0x07, target_id=0x21
                ),
                lineage=("rn_i.issue",),
            ),
        )
        ledger_state = ledger_issue.state
        network_state = self.activate_all(network_issue.state)

        network_state = self.apply(
            self.network,
            network_state,
            ChiNetworkCaptureToRouter("rn_to_xp"),
        ).state
        network_state = self.apply(
            self.network,
            network_state,
            ChiNetworkRouterToConnection("xp_to_home"),
        ).state
        network_state = self.tick(network_state, "xp_to_home")

        request_delivery = self.network.peek_delivery(
            network_state, "xp_to_home"
        )
        self.assertIsNotNone(request_delivery)
        assert request_delivery is not None
        home_accept = self.apply(
            self.home,
            home_state,
            ChiDirectHomeAccept(request_delivery.packet.message),
        )
        request_drain = self.apply(
            self.network,
            network_state,
            ChiNetworkDrain("xp_to_home"),
        )
        home_state = home_accept.state
        network_state = request_drain.state

        home_service = self.apply(
            self.home, home_state, ChiDirectHomeService()
        )
        response = home_service.emissions[0]
        response_enqueue = self.apply(
            self.network,
            network_state,
            ChiNetworkEnqueue(
                "home_to_xp",
                ChiNetworkPacket.data(
                    response, source_id=0x21, target_id=0x07
                ),
                lineage=(*request_delivery.lineage, "home.service"),
            ),
        )
        home_state = home_service.state
        network_state = self.tick(
            response_enqueue.state, "home_to_xp"
        )
        network_state = self.apply(
            self.network,
            network_state,
            ChiNetworkCaptureToRouter("home_to_xp"),
        ).state
        network_state = self.apply(
            self.network,
            network_state,
            ChiNetworkRouterToConnection("xp_to_rn"),
        ).state
        network_state = self.tick(network_state, "xp_to_rn")

        response_delivery = self.network.peek_delivery(
            network_state, "xp_to_rn"
        )
        self.assertIsNotNone(response_delivery)
        assert response_delivery is not None
        complete = self.apply(
            self.requester,
            ledger_state,
            ChiReadNoSnpComplete(response_delivery.packet.message),
        )
        response_drain = self.apply(
            self.network,
            network_state,
            ChiNetworkDrain("xp_to_rn"),
        )
        ledger_state = complete.state
        network_state = response_drain.state

        for _ in range(2):
            for connection in self.system.transport_plan.hops_by_name:
                network_state = self.tick(
                    network_state, connection, active=False
                )

        self.assertEqual(0xD000_4020, complete.emissions[0].data)
        self.assertEqual(2, response_delivery.packet.message.data_id)
        self.assertGreaterEqual(len(response_delivery.lineage), 4)
        self.assertTrue(self.requester.is_quiescent(ledger_state))
        self.assertTrue(self.home.is_quiescent(home_state))
        self.assertTrue(self.network.is_quiescent(network_state))

    def test_pcredit_return_is_transparently_routed_as_req(self) -> None:
        returned = ChiPCrdReturnMessage(5)
        state = self.apply(
            self.network,
            self.network.initial_state(),
            ChiNetworkEnqueue(
                "rn_to_xp",
                ChiNetworkPacket.request(
                    returned,
                    source_id=self.profile.requester_node_id,
                    target_id=self.profile.home_node_id,
                ),
                lineage=("rn_i.pcredit_return",),
            ),
        ).state
        state = self.activate_all(state)
        state = self.apply(
            self.network,
            state,
            ChiNetworkCaptureToRouter("rn_to_xp"),
        ).state
        state = self.apply(
            self.network,
            state,
            ChiNetworkRouterToConnection("xp_to_home"),
        ).state
        state = self.tick(state, "xp_to_home")

        delivery = self.network.peek_delivery(state, "xp_to_home")

        self.assertIsNotNone(delivery)
        assert delivery is not None
        self.assertIs(returned, delivery.packet.message)
        self.assertIs(ChiChannelKind.REQ, delivery.packet.channel)
        self.assertIn("rn_i.pcredit_return", delivery.lineage)

    def test_participant_binding_resolves_profile_ports(self) -> None:
        requester, home, _ = self.participant_bindings()

        self.assertIs(
            self.system.spec.virtual_duts["rn_i"].port("tx_req"),
            requester.require_one_port(
                ChiChannelKind.REQ, TransportDirection.TRANSMIT
            ),
        )
        self.assertIs(
            self.system.spec.virtual_duts["home"].port("rx_req"),
            home.require_one_port(
                ChiChannelKind.REQ, TransportDirection.RECEIVE
            ),
        )

    def test_bound_participants_close_read_without_manual_handoffs(self) -> None:
        requester, home, router = self.participant_bindings()
        session = ChiReadNoSnpSystemSession(
            self.system,
            requester=requester,
            home=home,
            routers=(router,),
        )
        request = self.request()

        issued = session.step(
            session.initial_state(), ChiSubmitRead(requester.name, request)
        )
        self.assertIsNone(issued.fault)
        self.assertIsNone(issued.blocked)
        run = session.run_until_quiescent(issued.state, max_steps=256)

        self.assertTrue(run.ok)
        self.assertIsNone(run.blocked)
        self.assertTrue(session.is_quiescent(run.final_state))
        self.assertEqual(1, len(run.final_state.requester.completed))
        result = run.final_state.requester.completed[0]
        self.assertIs(request, result.request)
        self.assertEqual(0xD000_4020, result.data)
        self.assertEqual(2, result.response.data_id)
        completed = tuple(
            event
            for event in run.emissions
            if event.kind is ChiReadNoSnpSystemEventKind.COMPLETE
        )
        self.assertEqual(1, len(completed))
        network_kinds = tuple(
            event.detail.kind
            for event in run.emissions
            if event.detail is not None
        )
        self.assertEqual(2, network_kinds.count(ChiNetworkEventKind.ROUTER_ACCEPT))
        self.assertEqual(2, network_kinds.count(ChiNetworkEventKind.ROUTER_FORWARD))

    def test_address_decode_nderr_closes_over_router_topology(self) -> None:
        requester, home, router = self.participant_bindings()
        address_home = ChiAddressHomeNode(
            "home",
            self.profile,
            AddressSpace(
                (
                    MemoryRegion(
                        "mapped",
                        self.profile.data_bytes,
                        base_address=0x8000,
                    ),
                )
            ),
            request_capacity=1,
        )
        error_home = ChiParticipantBinding(
            home.name,
            home.dut,
            address_home,
            home.ports,
            home.node_ids,
        )

        def resolve(
            feature,
            requester_capabilities,
            home_capabilities,
        ):
            return resolve_chi_system(
                self.system,
                facets=(
                    ChiBehaviorFacet.from_binding(
                        requester,
                        ChiFacetKind.TRANSACTION,
                    ),
                    ChiBehaviorFacet.from_binding(
                        error_home,
                        ChiFacetKind.TRANSACTION,
                    ),
                    ChiBehaviorFacet.from_binding(
                        router,
                        ChiFacetKind.FORWARDING,
                    ),
                ),
                feature_contract=ChiFeatureContract(
                    {"requester": requester.name},
                    frozenset((feature,)),
                ),
                authority_contract=ChiCoherenceAuthorityContract(
                    authorities=(
                        ChiHomeAuthority(
                            self.HOME_ADDRESS_CLAIM,
                            error_home.name,
                        ),
                    ),
                ),
                feature_address_claim=self.HOME_ADDRESS_CLAIM,
                participant_capabilities=(
                    ChiParticipantCapability(
                        requester.name,
                        requester_capabilities,
                    ),
                    ChiParticipantCapability(
                        error_home.name,
                        home_capabilities,
                    ),
                ),
            )

        resolved = resolve(
            CHI_FEATURE_READ_NO_SNP_NDERR,
            CHI_READ_NO_SNP_NDERR_REQUESTER_CAPABILITIES,
            CHI_READ_NO_SNP_NDERR_HOME_CAPABILITIES,
        )
        self.assertTrue(resolved.is_closed)
        self.assertTrue(
            resolved.capabilities.supports(
                CHI_FEATURE_READ_NO_SNP_NDERR
            )
        )
        session = ChiReadNoSnpSystemSession.from_resolved(resolved)
        self.assertEqual(
            frozenset((ChiRespErr.OK, ChiRespErr.NDERR)),
            session.enabled_response_errors,
        )
        request = ChiReadNoSnpMessage(
            transaction_id=9,
            address=0x9000,
            size=4,
            order=0,
            allow_retry=True,
            protocol_credit_type=0,
            expect_completion_ack=False,
            memory_attributes=0,
        )

        issued = session.step(
            session.initial_state(),
            ChiSubmitRead(requester.name, request),
        )
        self.assertIsNone(issued.fault)
        self.assertIsNone(issued.blocked)
        run = session.run_until_quiescent(issued.state, max_steps=256)

        self.assertTrue(run.ok)
        self.assertTrue(session.is_quiescent(run.final_state))
        self.assertEqual(1, len(run.final_state.requester.completed))
        result = run.final_state.requester.completed[0]
        self.assertFalse(result.succeeded)
        self.assertIs(ChiRespErr.NDERR, result.response_error)
        self.assertIsNone(result.data)
        self.assertEqual(0, result.response.data)
        self.assertEqual(
            self.profile.expected_data_id(request.address),
            result.response.data_id,
        )
        self.assertFalse(run.final_state.home.pending)
        self.assertEqual(1, run.final_state.home.completed_count)
        completed = tuple(
            event
            for event in run.emissions
            if event.kind is ChiReadNoSnpSystemEventKind.COMPLETE
        )
        self.assertEqual(1, len(completed))
        self.assertIs(
            ChiRespErr.NDERR,
            completed[0].packet.message.response_error,
        )
        self.assertEqual(
            self.profile.home_node_id,
            completed[0].packet.source_id,
        )
        self.assertEqual(
            self.profile.requester_node_id,
            completed[0].packet.target_id,
        )
        self.assertGreaterEqual(len(completed[0].lineage), 4)

        outside = ChiReadNoSnpMessage(
            transaction_id=10,
            address=0x1_0000,
            size=4,
            order=0,
            allow_retry=True,
            protocol_credit_type=0,
            expect_completion_ack=False,
            memory_attributes=0,
        )
        rejected = session.step(
            session.initial_state(),
            ChiSubmitRead(requester.name, outside),
        )
        self.assertIsNotNone(rejected.fault)
        self.assertIn("authority", rejected.fault.reason)
        self.assertFalse(rejected.emissions)

        base_resolved = resolve(
            CHI_FEATURE_READ_NO_SNP,
            CHI_READ_NO_SNP_REQUESTER_CAPABILITIES,
            CHI_READ_NO_SNP_HOME_CAPABILITIES,
        )
        self.assertTrue(base_resolved.is_closed)
        base_session = ChiReadNoSnpSystemSession.from_resolved(base_resolved)
        self.assertEqual(
            frozenset((ChiRespErr.OK,)),
            base_session.enabled_response_errors,
        )
        base_issued = base_session.step(
            base_session.initial_state(),
            ChiSubmitRead(requester.name, request),
        )
        base_run = base_session.run_until_quiescent(
            base_issued.state,
            max_steps=256,
        )

        self.assertFalse(base_run.ok)
        self.assertEqual(1, len(base_run.violations))
        self.assertIn(
            "NDERR",
            base_run.violations[0].fault.reason,
        )
        self.assertTrue(base_run.final_state.requester.outstanding)
        self.assertTrue(base_run.final_state.home.pending)
        self.assertFalse(base_run.final_state.requester.completed)

    def test_read_session_rejects_incomplete_participant_binding(self) -> None:
        requester, home, router = self.participant_bindings()
        incomplete = ChiParticipantBinding(
            requester.name,
            requester.dut,
            requester.component,
            (requester.ports[0],),
            requester.node_ids,
        )

        with self.assertRaisesRegex(ValueError, "receive DAT port"):
            ChiReadNoSnpSystemSession(
                self.system,
                requester=incomplete,
                home=home,
                routers=(router,),
            )

    def test_submit_rolls_back_ledger_when_first_hop_is_full(self) -> None:
        requester, home, router = self.participant_bindings()
        session = ChiReadNoSnpSystemSession(
            self.system,
            requester=requester,
            home=home,
            routers=(router,),
        )
        first = self.request(3)
        accepted = session.step(
            session.initial_state(), ChiSubmitRead(requester.name, first)
        )

        blocked = session.step(
            accepted.state,
            ChiSubmitRead(requester.name, self.request(4)),
        )

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(accepted.state, blocked.state)
        self.assertEqual(
            (first.semantic_key,), tuple(blocked.state.requester.outstanding)
        )

    def test_read_session_requires_end_to_end_return_route(self) -> None:
        requester, home, router = self.participant_bindings()
        request_only_router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=self.router.ingress_ports,
            egress_ports=self.router.egress_ports,
            routes=(
                ChiExactNodeRoute(
                    self.profile.home_node_id,
                    "to_home",
                    frozenset((ChiChannelKind.REQ,)),
                ),
            ),
        )
        incomplete_router = ChiParticipantBinding(
            router.name,
            router.dut,
            request_only_router,
            router.ports,
        )

        with self.assertRaisesRegex(ValueError, "DAT route"):
            ChiReadNoSnpSystemSession(
                self.system,
                requester=requester,
                home=home,
                routers=(incomplete_router,),
            )

    def test_router_full_preserves_the_upstream_capture(self) -> None:
        state = self.network.initial_state()
        state = self.apply(
            self.network,
            state,
            ChiNetworkEnqueue(
                "rn_to_xp",
                ChiNetworkPacket.request(
                    self.request(3), source_id=0x07, target_id=0x21
                ),
            ),
        ).state
        state = self.tick(state, "rn_to_xp", 3)
        state = self.apply(
            self.network,
            state,
            ChiNetworkCaptureToRouter("rn_to_xp"),
        ).state

        state = self.apply(
            self.network,
            state,
            ChiNetworkEnqueue(
                "rn_to_xp",
                ChiNetworkPacket.request(
                    self.request(4), source_id=0x07, target_id=0x21
                ),
            ),
        ).state
        state = self.tick(state, "rn_to_xp", 2)
        self.assertIsNotNone(
            self.network.peek_delivery(state, "rn_to_xp")
        )

        blocked = self.network.step(
            state, ChiNetworkCaptureToRouter("rn_to_xp")
        )

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertEqual(1, state.paths["rn_to_xp"].receiver.depth)
        self.assertEqual(1, state.routers["xp0"].depth)

    def test_downstream_full_preserves_the_router_packet(self) -> None:
        state = self.network.initial_state()
        state = self.apply(
            self.network,
            state,
            ChiNetworkEnqueue(
                "rn_to_xp",
                ChiNetworkPacket.request(
                    self.request(3), source_id=0x07, target_id=0x21
                ),
            ),
        ).state
        state = self.tick(state, "rn_to_xp", 3)
        state = self.apply(
            self.network,
            state,
            ChiNetworkCaptureToRouter("rn_to_xp"),
        ).state
        state = self.apply(
            self.network,
            state,
            ChiNetworkEnqueue(
                "xp_to_home",
                ChiNetworkPacket.request(
                    self.request(4), source_id=0x07, target_id=0x21
                ),
            ),
        ).state

        blocked = self.network.step(
            state, ChiNetworkRouterToConnection("xp_to_home")
        )

        self.assertIsNotNone(blocked.blocked)
        self.assertIs(state, blocked.state)
        self.assertEqual(1, state.routers["xp0"].depth)
        self.assertEqual(1, state.paths["xp_to_home"].transmitter.depth)

    def test_same_session_type_runs_a_direct_topology_without_router(self) -> None:
        system = self.build_direct_request_system().elaborate()
        network = ChiTransportNetworkSession(system)
        request = self.request()
        state = self.apply(
            network,
            network.initial_state(),
            ChiNetworkEnqueue(
                "direct_req",
                ChiNetworkPacket.request(
                    request, source_id=0x07, target_id=0x21
                ),
                lineage=("direct_rn.issue",),
            ),
        ).state
        for _ in range(3):
            state = self.apply(
                network, state, ChiNetworkTick("direct_req")
            ).state

        delivery = network.peek_delivery(state, "direct_req")
        self.assertIsNotNone(delivery)
        assert delivery is not None
        self.assertEqual(
            VirtualDutPortRef("direct_rn", "tx_req"),
            delivery.transmitter,
        )
        self.assertEqual(
            VirtualDutPortRef("direct_home", "rx_req"),
            delivery.receiver,
        )
        self.assertIs(request, delivery.packet.message)
        self.assertEqual("direct_rn.issue", delivery.lineage[0])

        state = self.apply(
            network, state, ChiNetworkDrain("direct_req")
        ).state
        for _ in range(2):
            state = self.apply(
                network,
                state,
                ChiNetworkTick("direct_req", active=False),
            ).state
        self.assertTrue(network.is_quiescent(state))

    def test_router_route_must_match_the_connected_channel_profile(self) -> None:
        incompatible = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_rn", "from_home"),
            egress_ports=("to_rn", "to_home"),
            routes=(
                ChiExactNodeRoute(
                    self.profile.home_node_id,
                    "to_home",
                    frozenset((ChiChannelKind.REQ,)),
                ),
                ChiExactNodeRoute(
                    self.profile.requester_node_id,
                    "to_rn",
                    frozenset(
                        (ChiChannelKind.RSP, ChiChannelKind.DAT)
                    ),
                ),
            ),
        )

        with self.assertRaisesRegex(
            ValueError, "channels unavailable.*rsp"
        ):
            ChiTransportNetworkSession(
                self.system, routers={"xp0": incompatible}
            )


if __name__ == "__main__":
    unittest.main()
