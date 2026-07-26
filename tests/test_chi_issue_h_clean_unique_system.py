from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.participants.capability import (
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiRespCode,
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiCleanUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpCleanInvalidMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiAdvanceCoherenceNetwork,
    ChiCapabilityGapKind,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiFeatureContract,
    ChiFlowProjectionGapKind,
    ChiHomeAuthority,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiSubmitCleanUnique,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiSnpChannelProfile,
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


class ChiIssueHCleanUniqueSystemTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC1EA
    DIRTY_DATA = (1 << 401) | 0xD17A

    @staticmethod
    def port(
        name: str,
        direction: TransportDirection,
    ) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    @staticmethod
    def link_profile(
        name: str,
        channels: frozenset[ChiChannelKind],
    ) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=(
                ChiReqChannelProfile(
                    ChiIssueHReqProfile(),
                    (1,),
                    f"{name}.req",
                )
                if ChiChannelKind.REQ in channels
                else None
            ),
            response=(
                ChiRspChannelProfile(
                    ChiIssueHRspProfile(),
                    1,
                    f"{name}.rsp",
                )
                if ChiChannelKind.RSP in channels
                else None
            ),
            snoop=(
                ChiSnpChannelProfile(
                    ChiIssueHSnpProfile(),
                    1,
                    f"{name}.snp",
                )
                if ChiChannelKind.SNP in channels
                else None
            ),
            data=(
                ChiDatChannelProfile(
                    ChiIssueHDatProfile(data_width=512),
                    1,
                    f"{name}.dat",
                )
                if ChiChannelKind.DAT in channels
                else None
            ),
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    def build_resolved(
        self,
        *,
        via_xp: bool,
        peer_state: ChiCacheState = ChiCacheState.SC,
        include_peer_rsp: bool = True,
        requester_data: int | None = None,
    ):
        shared_dirty_peer = peer_state is ChiCacheState.SD
        builder = SystemProtocolBuilder(
            (
                "chi_clean_unique_shared_dirty_peer_via_xp"
                if shared_dirty_peer and via_xp
                else "chi_clean_unique_shared_dirty_peer_direct"
                if shared_dirty_peer
                else "chi_clean_unique_clean_peer_via_xp"
                if via_xp
                else "chi_clean_unique_clean_peer_direct"
            )
        )
        if via_xp:
            self._add_xp_duts(builder)
            connection_specs = self._xp_connections(
                include_peer_rsp,
                include_peer_dat=shared_dirty_peer,
            )
            home_claim_port = "rx_from_xp"
        else:
            self._add_direct_duts(builder)
            connection_specs = self._direct_connections(
                include_peer_rsp,
                include_peer_dat=shared_dirty_peer,
            )
            home_claim_port = "rx_req_ack"
        for name, transmitter, receiver, channels in connection_specs:
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=self.link_profile(name, channels),
            )

        claim_name = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                claim_name,
                VirtualDutPortRef("hn0", home_claim_port),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        if via_xp:
            requester_channels = {
                "tx_to_xp": frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
                "rx_from_xp": frozenset((ChiChannelKind.RSP,)),
            }
            peer_channels = {
                "tx_to_xp": frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if shared_dirty_peer
                            else ()
                        ),
                    )
                ),
                "rx_from_xp": frozenset((ChiChannelKind.SNP,)),
            }
        else:
            requester_channels = {
                "tx_req_ack": frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
                "rx_comp": frozenset((ChiChannelKind.RSP,)),
            }
            peer_channels = {
                "tx_rsp": frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if shared_dirty_peer
                            else ()
                        ),
                    )
                ),
                "rx_snp": frozenset((ChiChannelKind.SNP,)),
            }
        resident_data = (
            self.DIRTY_DATA if shared_dirty_peer else self.DATA
        )
        requester_assembly = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.REQUESTER,
            self.HOME,
            port_channels=requester_channels,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SC,
                    (
                        resident_data
                        if requester_data is None
                        else requester_data
                    ),
                ),
            ),
            participant_name="requester",
            binding_name="rn0",
        )
        peer_assembly = bind_chi_issue_h_cache_lines(
            duts["rn1"],
            self.PEER,
            self.HOME,
            port_channels=peer_channels,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    peer_state,
                    resident_data,
                ),
            ),
            participant_name="peer",
            binding_name="rn1",
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.DATA,
                    sharers=(
                        frozenset((self.REQUESTER, self.PEER))
                        if peer_state
                        in (ChiCacheState.SC, ChiCacheState.SD)
                        else frozenset()
                    ),
                    unique_owner=(
                        self.PEER
                        if peer_state is ChiCacheState.UD
                        else None
                    ),
                    shared_dirty_owner=(
                        self.PEER if shared_dirty_peer else None
                    ),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
            allow_dirty_data_transfer=shared_dirty_peer,
        )
        home_binding = self._home_binding(
            duts,
            home,
            via_xp=via_xp,
            include_peer_dat=shared_dirty_peer,
        )
        facets = [
            requester_assembly.facets.facets[0],
            peer_assembly.facets.facets[0],
            ChiBehaviorFacet.from_binding(
                home_binding,
                ChiFacetKind.TRANSACTION,
            ),
        ]
        if via_xp:
            facets.append(
                ChiBehaviorFacet.from_binding(
                    self._router_binding(
                        duts,
                        include_peer_dat=shared_dirty_peer,
                    ),
                    ChiFacetKind.FORWARDING,
                )
            )

        required_feature = (
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            if shared_dirty_peer
            else CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        home_capabilities = (
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
            | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES
            if shared_dirty_peer
            else CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
        )
        snoopee_capabilities = (
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
            | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES
            if shared_dirty_peer
            else CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
        )
        system_capabilities = {
            CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE
        }
        if shared_dirty_peer:
            system_capabilities.add(
                CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE
            )
        return resolve_chi_system(
            system,
            facets=tuple(facets),
            feature_contract=ChiFeatureContract(
                {"requester": "rn0"},
                frozenset((required_feature,)),
            ),
            authority_contract=ChiCoherenceAuthorityContract(
                authorities=(
                    ChiHomeAuthority(
                        claim_name,
                        "hn0",
                        "coherent_agents",
                    ),
                ),
                domains=(
                    ChiCoherenceDomain(
                        "coherent_agents",
                        frozenset(("rn0", "rn1")),
                    ),
                ),
            ),
            feature_address_claim=claim_name,
            participant_capabilities=(
                ChiParticipantCapability(
                    "rn0",
                    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "hn0",
                    home_capabilities,
                ),
                ChiParticipantCapability(
                    "rn1",
                    snoopee_capabilities,
                ),
            ),
            system_capabilities=frozenset(system_capabilities),
        )

    def _add_direct_duts(self, builder: SystemProtocolBuilder) -> None:
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_req_ack": self.port(
                        "tx_req_ack",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_comp": self.port(
                        "rx_comp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "rn1",
                {
                    "tx_rsp": self.port(
                        "tx_rsp",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_snp": self.port(
                        "rx_snp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "hn0",
                {
                    "rx_req_ack": self.port(
                        "rx_req_ack",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_comp": self.port(
                        "tx_comp",
                        TransportDirection.TRANSMIT,
                    ),
                    "tx_snp": self.port(
                        "tx_snp",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_peer_rsp": self.port(
                        "rx_peer_rsp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )

    def _direct_connections(
        self,
        include_peer_rsp: bool,
        *,
        include_peer_dat: bool,
    ):
        items = [
            (
                "request_ack",
                VirtualDutPortRef("rn0", "tx_req_ack"),
                VirtualDutPortRef("hn0", "rx_req_ack"),
                frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
            ),
            (
                "completion",
                VirtualDutPortRef("hn0", "tx_comp"),
                VirtualDutPortRef("rn0", "rx_comp"),
                frozenset((ChiChannelKind.RSP,)),
            ),
            (
                "snoop",
                VirtualDutPortRef("hn0", "tx_snp"),
                VirtualDutPortRef("rn1", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
        ]
        peer_return_channels = {
            (
                ChiChannelKind.RSP
                if include_peer_rsp
                else ChiChannelKind.REQ
            )
        }
        if include_peer_dat:
            peer_return_channels.add(ChiChannelKind.DAT)
        items.append(
            (
                "snoop_response",
                VirtualDutPortRef("rn1", "tx_rsp"),
                VirtualDutPortRef("hn0", "rx_peer_rsp"),
                frozenset(peer_return_channels),
            )
        )
        return tuple(items)

    def _add_xp_duts(self, builder: SystemProtocolBuilder) -> None:
        for name in ("rn0", "rn1", "hn0"):
            builder.add_dut(
                VirtualDut(
                    name,
                    {
                        "tx_to_xp": self.port(
                            "tx_to_xp",
                            TransportDirection.TRANSMIT,
                        ),
                        "rx_from_xp": self.port(
                            "rx_from_xp",
                            TransportDirection.RECEIVE,
                        ),
                    },
                )
            )
        builder.add_dut(
            VirtualDut(
                "xp0",
                {
                    **{
                        f"from_{name}": self.port(
                            f"from_{name}",
                            TransportDirection.RECEIVE,
                        )
                        for name in ("rn0", "rn1", "hn0")
                    },
                    **{
                        f"to_{name}": self.port(
                            f"to_{name}",
                            TransportDirection.TRANSMIT,
                        )
                        for name in ("rn0", "rn1", "hn0")
                    },
                },
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
            )
        )

    def _xp_connections(
        self,
        include_peer_rsp: bool,
        *,
        include_peer_dat: bool,
    ):
        home_return_channels = {
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
        }
        if include_peer_dat:
            home_return_channels.add(ChiChannelKind.DAT)
        items = [
            (
                "rn0_to_xp",
                VirtualDutPortRef("rn0", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_rn0"),
                frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
            ),
            (
                "hn0_to_xp",
                VirtualDutPortRef("hn0", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_hn0"),
                frozenset(
                    (ChiChannelKind.RSP, ChiChannelKind.SNP)
                ),
            ),
            (
                "xp_to_rn0",
                VirtualDutPortRef("xp0", "to_rn0"),
                VirtualDutPortRef("rn0", "rx_from_xp"),
                frozenset((ChiChannelKind.RSP,)),
            ),
            (
                "xp_to_rn1",
                VirtualDutPortRef("xp0", "to_rn1"),
                VirtualDutPortRef("rn1", "rx_from_xp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "xp_to_hn0",
                VirtualDutPortRef("xp0", "to_hn0"),
                VirtualDutPortRef("hn0", "rx_from_xp"),
                frozenset(home_return_channels),
            ),
        ]
        peer_return_channels = {
            (
                ChiChannelKind.RSP
                if include_peer_rsp
                else ChiChannelKind.REQ
            )
        }
        if include_peer_dat:
            peer_return_channels.add(ChiChannelKind.DAT)
        items.append(
            (
                "rn1_to_xp",
                VirtualDutPortRef("rn1", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_rn1"),
                frozenset(peer_return_channels),
            )
        )
        return tuple(items)

    def _home_binding(
        self,
        duts,
        home: ChiCoherentHomeNode,
        *,
        via_xp: bool,
        include_peer_dat: bool,
    ) -> ChiParticipantBinding:
        item = ChiParticipantPortBinding
        if via_xp:
            ports = (
                item(
                    duts["hn0"].port("tx_to_xp"),
                    frozenset(
                        (ChiChannelKind.RSP, ChiChannelKind.SNP)
                    ),
                ),
                item(
                    duts["hn0"].port("rx_from_xp"),
                    frozenset(
                        (
                            ChiChannelKind.REQ,
                            ChiChannelKind.RSP,
                            *(
                                (ChiChannelKind.DAT,)
                                if include_peer_dat
                                else ()
                            ),
                        )
                    ),
                ),
            )
        else:
            ports = (
                item(
                    duts["hn0"].port("rx_req_ack"),
                    frozenset(
                        (ChiChannelKind.REQ, ChiChannelKind.RSP)
                    ),
                ),
                item(
                    duts["hn0"].port("tx_comp"),
                    frozenset((ChiChannelKind.RSP,)),
                ),
                item(
                    duts["hn0"].port("tx_snp"),
                    frozenset((ChiChannelKind.SNP,)),
                ),
                item(
                    duts["hn0"].port("rx_peer_rsp"),
                    frozenset(
                        (
                            ChiChannelKind.RSP,
                            *(
                                (ChiChannelKind.DAT,)
                                if include_peer_dat
                                else ()
                            ),
                        )
                    ),
                ),
            )
        return ChiParticipantBinding(
            "hn0",
            duts["hn0"],
            home,
            ports,
            frozenset((self.HOME,)),
        )

    def _router_binding(
        self,
        duts,
        *,
        include_peer_dat: bool,
    ) -> ChiParticipantBinding:
        home_route_channels = {
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
        }
        peer_return_channels = {ChiChannelKind.RSP}
        if include_peer_dat:
            home_route_channels.add(ChiChannelKind.DAT)
            peer_return_channels.add(ChiChannelKind.DAT)
        router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_rn0", "from_rn1", "from_hn0"),
            egress_ports=("to_rn0", "to_rn1", "to_hn0"),
            routes=(
                ChiExactNodeRoute(
                    self.REQUESTER,
                    "to_rn0",
                    frozenset((ChiChannelKind.RSP,)),
                ),
                ChiExactNodeRoute(
                    self.PEER,
                    "to_rn1",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    self.HOME,
                    "to_hn0",
                    frozenset(home_route_channels),
                ),
            ),
            queue_capacity=1,
        )
        channels = {
            "from_rn0": frozenset(
                (ChiChannelKind.REQ, ChiChannelKind.RSP)
            ),
            "from_rn1": frozenset(peer_return_channels),
            "from_hn0": frozenset(
                (ChiChannelKind.RSP, ChiChannelKind.SNP)
            ),
            "to_rn0": frozenset((ChiChannelKind.RSP,)),
            "to_rn1": frozenset((ChiChannelKind.SNP,)),
            "to_hn0": frozenset(home_route_channels),
        }
        return ChiParticipantBinding(
            "xp0",
            duts["xp0"],
            router,
            tuple(
                ChiParticipantPortBinding(
                    duts["xp0"].port(name),
                    offered,
                )
                for name, offered in channels.items()
            ),
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def run_clean_unique(self, resolved):
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        events = []
        issued = self.apply(
            session,
            state,
            ChiSubmitCleanUnique(
                self.REQUESTER,
                ChiCleanUniqueMessage(0x31, self.ADDRESS),
            ),
        )
        state = issued.state
        events.extend(issued.emissions)
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            events.extend(advanced.emissions)
        else:
            self.fail("CleanUnique did not quiesce within 1024 microsteps")
        return session, state, tuple(events)

    def assert_clean_unique_result(self, session, state, events) -> None:
        endpoint_events = tuple(
            event
            for event in events
            if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
        )
        self.assertEqual(
            (
                ChiCleanUniqueMessage,
                ChiSnpCleanInvalidMessage,
                ChiSnpRespMessage,
                ChiCompMessage,
                ChiCompAckMessage,
            ),
            tuple(type(event.packet.message) for event in endpoint_events),
        )
        self.assertEqual(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.SNP,
                ChiChannelKind.RSP,
                ChiChannelKind.RSP,
                ChiChannelKind.RSP,
            ),
            tuple(event.packet.channel for event in endpoint_events),
        )
        request, snoop, snoop_response, completion, completion_ack = (
            event.packet.message for event in endpoint_events
        )
        self.assertEqual(0x31, request.transaction_id)
        self.assertEqual(snoop.transaction_id, snoop_response.transaction_id)
        self.assertIs(ChiRespCode.I, snoop_response.response)
        self.assertEqual(0x31, completion.transaction_id)
        self.assertIs(ChiRespCode.UC, completion.response)
        self.assertEqual(
            completion.data_buffer_id,
            completion_ack.transaction_id,
        )
        self.assertNotEqual(
            completion.transaction_id,
            completion_ack.transaction_id,
        )

        home_state = state.coherence.home
        requester_state = state.coherence.request_nodes[self.REQUESTER]
        peer_state = state.coherence.request_nodes[self.PEER]
        entry = home_state.directory[self.ADDRESS]
        self.assertEqual(self.DATA, entry.data)
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIs(
            ChiCacheState.UC,
            requester_state.permissions[self.ADDRESS],
        )
        self.assertEqual(
            self.DATA,
            requester_state.cache.lines[self.ADDRESS].data,
        )
        self.assertIs(
            ChiCacheState.I,
            peer_state.permissions[self.ADDRESS],
        )
        self.assertNotIn(self.ADDRESS, peer_state.cache.lines)
        self.assertFalse(home_state.pending)
        self.assertFalse(requester_state.pending_transactions)
        self.assertFalse(peer_state.pending_transactions)
        self.assertTrue(session.is_quiescent(state))

    def assert_shared_dirty_clean_unique_result(
        self,
        session,
        state,
        events,
    ) -> None:
        endpoint_events = tuple(
            event
            for event in events
            if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
        )
        self.assertEqual(
            (
                ChiCleanUniqueMessage,
                ChiSnpCleanInvalidMessage,
                ChiSnpRespDataMessage,
                ChiCompMessage,
                ChiCompAckMessage,
            ),
            tuple(type(event.packet.message) for event in endpoint_events),
        )
        self.assertEqual(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.SNP,
                ChiChannelKind.DAT,
                ChiChannelKind.RSP,
                ChiChannelKind.RSP,
            ),
            tuple(event.packet.channel for event in endpoint_events),
        )
        request, snoop, snoop_data, completion, completion_ack = (
            event.packet.message for event in endpoint_events
        )
        self.assertEqual(0x31, request.transaction_id)
        self.assertEqual(snoop.transaction_id, snoop_data.transaction_id)
        self.assertIs(ChiRespCode.I_PD, snoop_data.response)
        self.assertEqual(self.DIRTY_DATA, snoop_data.data)
        self.assertEqual(0x31, completion.transaction_id)
        self.assertIs(ChiRespCode.UC, completion.response)
        self.assertEqual(
            completion.data_buffer_id,
            completion_ack.transaction_id,
        )

        home_state = state.coherence.home
        requester_state = state.coherence.request_nodes[self.REQUESTER]
        peer_state = state.coherence.request_nodes[self.PEER]
        entry = home_state.directory[self.ADDRESS]
        self.assertEqual(self.DIRTY_DATA, entry.data)
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        self.assertIs(
            ChiCacheState.UC,
            requester_state.permissions[self.ADDRESS],
        )
        self.assertEqual(
            self.DIRTY_DATA,
            requester_state.cache.lines[self.ADDRESS].data,
        )
        self.assertIs(
            ChiCacheState.I,
            peer_state.permissions[self.ADDRESS],
        )
        self.assertNotIn(self.ADDRESS, peer_state.cache.lines)
        self.assertFalse(home_state.pending)
        self.assertFalse(requester_state.pending_transactions)
        self.assertFalse(peer_state.pending_transactions)
        self.assertTrue(session.is_quiescent(state))

    def test_direct_and_xp_topologies_run_clean_unique_to_quiescence(
        self,
    ) -> None:
        for via_xp in (False, True):
            with self.subTest(via_xp=via_xp):
                resolved = self.build_resolved(via_xp=via_xp)
                self.assertTrue(resolved.is_closed)

                session, state, events = self.run_clean_unique(resolved)

                self.assert_clean_unique_result(
                    session,
                    state,
                    events,
                )

    def test_direct_and_xp_topologies_run_shared_dirty_clean_unique(
        self,
    ) -> None:
        for via_xp in (False, True):
            with self.subTest(via_xp=via_xp):
                resolved = self.build_resolved(
                    via_xp=via_xp,
                    peer_state=ChiCacheState.SD,
                )
                self.assertTrue(resolved.is_closed)

                session, state, events = self.run_clean_unique(resolved)

                self.assert_shared_dirty_clean_unique_result(
                    session,
                    state,
                    events,
                )

    def test_xp_projection_closes_five_flow_kinds_without_dat(self) -> None:
        resolved = self.build_resolved(via_xp=True)

        evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        self.assertEqual(
            {
                "clean_unique_request",
                "clean_unique_snoop[hn0->rn1]",
                "clean_unique_snoop_response[rn1->hn0]",
                "clean_unique_completion",
                "clean_unique_completion_ack",
            },
            set(evidence.flows),
        )
        self.assertEqual(
            {
                ("rn0", "hn0", ChiChannelKind.REQ): (
                    "rn0_to_xp",
                    "xp_to_hn0",
                ),
                ("hn0", "rn1", ChiChannelKind.SNP): (
                    "hn0_to_xp",
                    "xp_to_rn1",
                ),
                ("rn1", "hn0", ChiChannelKind.RSP): (
                    "rn1_to_xp",
                    "xp_to_hn0",
                ),
                ("hn0", "rn0", ChiChannelKind.RSP): (
                    "hn0_to_xp",
                    "xp_to_rn0",
                ),
                ("rn0", "hn0", ChiChannelKind.RSP): (
                    "rn0_to_xp",
                    "xp_to_hn0",
                ),
            },
            {
                (flow.source, flow.target, flow.channel): flow.connections
                for flow in resolved.flow_projection.flows
            },
        )
        self.assertNotIn(
            ChiChannelKind.DAT,
            {flow.channel for flow in resolved.flow_projection.flows},
        )

    def test_xp_shared_dirty_feature_adds_one_snoop_dat_flow(self) -> None:
        resolved = self.build_resolved(
            via_xp=True,
            peer_state=ChiCacheState.SD,
        )

        dirty_evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
        )
        self.assertEqual(
            {"clean_unique_snoop_data[rn1->hn0]"},
            set(dirty_evidence.flows),
        )
        dirty_flow = dirty_evidence.flows[
            "clean_unique_snoop_data[rn1->hn0]"
        ]
        self.assertIs(ChiChannelKind.DAT, dirty_flow.channel)
        self.assertEqual(
            ("rn1_to_xp", "xp_to_hn0"),
            dirty_flow.connections,
        )

        clean_evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        self.assertNotIn(
            ChiChannelKind.DAT,
            {flow.channel for flow in clean_evidence.flows.values()},
        )
        self.assertEqual(
            1,
            sum(
                flow.channel is ChiChannelKind.DAT
                for flow in resolved.flow_projection.flows
            ),
        )

    def test_unique_dirty_peer_is_rejected_before_network_run(self) -> None:
        resolved = self.build_resolved(
            via_xp=False,
            peer_state=ChiCacheState.UD,
        )
        self.assertTrue(resolved.is_closed)

        with self.assertRaisesRegex(ValueError, "dirty|UD"):
            ChiCoherenceNetworkSession.from_resolved(resolved)

    def test_monitor_rejects_inconsistent_clean_and_shared_dirty_data(
        self,
    ) -> None:
        resolved = self.build_resolved(
            via_xp=False,
            peer_state=ChiCacheState.SD,
            requester_data=self.DATA,
        )
        self.assertTrue(resolved.is_closed)

        with self.assertRaisesRegex(
            ValueError,
            "shared data.*differs from shared-dirty owner",
        ):
            ChiCoherenceNetworkSession.from_resolved(resolved)

    def test_missing_peer_rsp_route_is_a_construction_gap(self) -> None:
        resolved = self.build_resolved(
            via_xp=True,
            include_peer_rsp=False,
        )

        self.assertFalse(resolved.is_closed)
        requirement = (
            f"{CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS.name}:"
            "clean_unique_snoop_response[rn1->hn0]"
        )
        projection_gap = next(
            gap
            for gap in resolved.flow_projection.gaps
            if gap.requirement == requirement
        )
        self.assertIs(
            ChiFlowProjectionGapKind.CHANNEL,
            projection_gap.kind,
        )
        capability_gap = next(
            gap
            for gap in resolved.capabilities.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            )
            if gap.subject
            == "clean_unique_snoop_response[rn1->hn0]"
        )
        self.assertIs(ChiCapabilityGapKind.FLOW, capability_gap.kind)


if __name__ == "__main__":
    unittest.main()
