from __future__ import annotations

from collections import Counter
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_UNIQUE_HOME_CAPABILITIES,
    CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES,
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
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiReadNotSharedDirtyMessage,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_MESI_NO_SD_REQUIRED_FEATURES,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
    CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE,
    ChiAdvanceCoherenceNetwork,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkSession,
    ChiCoherenceNetworkState,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCoherentRead,
    ChiWriteUniqueCacheLine,
    resolve_chi_system,
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


class ChiIssueHCoherenceNetworkTest(unittest.TestCase):
    """Run clean, dirty, and MESI downgrade paths through one caller-built NoC.

    All protocol packets cross ``xp0``.  In particular, the two snoops are
    separate packets sharing the same Home egress connection.  Its capacity
    is one, so the composite runtime must retain the second packet instead of
    dropping it when the first packet occupies the transport transmitter.
    """

    REQUESTER = 0x07
    FIRST_SNOOPEE = 0x08
    SECOND_SNOOPEE = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC0DE

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
        *,
        data_width: int = 512,
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
                    ChiIssueHDatProfile(data_width=data_width),
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
        dirty: bool = False,
        mesi: bool = False,
        data_width: int = 512,
    ):
        if dirty and mesi:
            raise ValueError("select either dirty-unique or MESI read mode")
        uses_dirty_data = dirty or mesi
        builder = SystemProtocolBuilder(
            (
                "chi_mesi_read_not_shared_dirty_via_xp"
                if mesi
                else (
                    "chi_dirty_unique_via_xp"
                    if dirty
                    else "chi_clean_unique_via_xp"
                )
            )
        )
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_req_rsp": self.port(
                        "tx_req_rsp",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_dat": self.port(
                        "rx_dat",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        for name in ("rn1", "rn2"):
            builder.add_dut(
                VirtualDut(
                    name,
                    {
                        "rx_snp": self.port(
                            "rx_snp",
                            TransportDirection.RECEIVE,
                        ),
                        "tx_rsp": self.port(
                            "tx_rsp",
                            TransportDirection.TRANSMIT,
                        ),
                    },
                )
            )
        builder.add_dut(
            VirtualDut(
                "hn0",
                {
                    "rx_req_rsp": self.port(
                        "rx_req_rsp",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_dat_snp": self.port(
                        "tx_dat_snp",
                        TransportDirection.TRANSMIT,
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
                        for name in ("rn0", "rn1", "rn2", "hn0")
                    },
                    **{
                        f"to_{name}": self.port(
                            f"to_{name}",
                            TransportDirection.TRANSMIT,
                        )
                        for name in ("rn0", "rn1", "rn2", "hn0")
                    },
                },
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
            )
        )

        connection_specs = (
            (
                "rn0_to_xp",
                VirtualDutPortRef("rn0", "tx_req_rsp"),
                VirtualDutPortRef("xp0", "from_rn0"),
                frozenset((ChiChannelKind.REQ, ChiChannelKind.RSP)),
            ),
            (
                "rn1_to_xp",
                VirtualDutPortRef("rn1", "tx_rsp"),
                VirtualDutPortRef("xp0", "from_rn1"),
                frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if uses_dirty_data
                            else ()
                        ),
                    )
                ),
            ),
            (
                "rn2_to_xp",
                VirtualDutPortRef("rn2", "tx_rsp"),
                VirtualDutPortRef("xp0", "from_rn2"),
                frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if uses_dirty_data
                            else ()
                        ),
                    )
                ),
            ),
            (
                "hn0_to_xp",
                VirtualDutPortRef("hn0", "tx_dat_snp"),
                VirtualDutPortRef("xp0", "from_hn0"),
                frozenset((ChiChannelKind.DAT, ChiChannelKind.SNP)),
            ),
            (
                "xp_to_rn0",
                VirtualDutPortRef("xp0", "to_rn0"),
                VirtualDutPortRef("rn0", "rx_dat"),
                frozenset((ChiChannelKind.DAT,)),
            ),
            (
                "xp_to_rn1",
                VirtualDutPortRef("xp0", "to_rn1"),
                VirtualDutPortRef("rn1", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "xp_to_rn2",
                VirtualDutPortRef("xp0", "to_rn2"),
                VirtualDutPortRef("rn2", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "xp_to_hn0",
                VirtualDutPortRef("xp0", "to_hn0"),
                VirtualDutPortRef("hn0", "rx_req_rsp"),
                frozenset(
                    (
                        ChiChannelKind.REQ,
                        ChiChannelKind.RSP,
                        *((ChiChannelKind.DAT,) if uses_dirty_data else ()),
                    )
                ),
            ),
        )
        for name, transmitter, receiver, channels in connection_specs:
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=self.link_profile(
                    name,
                    channels,
                    data_width=data_width,
                ),
            )

        home_address_claim = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                home_address_claim,
                VirtualDutPortRef("hn0", "rx_req_rsp"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts
        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
        )
        snoopees = {
            "rn1": build_chi_cache_participant_fixture(
                "snoopee_1",
                self.FIRST_SNOOPEE,
                self.HOME,
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        (
                            ChiCacheState.UC
                            if uses_dirty_data
                            else ChiCacheState.SC
                        ),
                        self.DATA,
                    ),
                ),
            ),
            "rn2": build_chi_cache_participant_fixture(
                "snoopee_2",
                self.SECOND_SNOOPEE,
                self.HOME,
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        (
                            ChiCacheState.I
                            if uses_dirty_data
                            else ChiCacheState.SC
                        ),
                        None if uses_dirty_data else self.DATA,
                    ),
                ),
            ),
        }
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    self.DATA,
                    sharers=(
                        frozenset()
                        if uses_dirty_data
                        else frozenset(
                            (
                                self.FIRST_SNOOPEE,
                                self.SECOND_SNOOPEE,
                            )
                        )
                    ),
                    unique_owner=(
                        self.FIRST_SNOOPEE if uses_dirty_data else None
                    ),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
            allow_dirty_data_transfer=uses_dirty_data,
        )
        router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=(
                "from_rn0",
                "from_rn1",
                "from_rn2",
                "from_hn0",
            ),
            egress_ports=("to_rn0", "to_rn1", "to_rn2", "to_hn0"),
            routes=(
                ChiExactNodeRoute(
                    self.REQUESTER,
                    "to_rn0",
                    frozenset((ChiChannelKind.DAT,)),
                ),
                ChiExactNodeRoute(
                    self.FIRST_SNOOPEE,
                    "to_rn1",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    self.SECOND_SNOOPEE,
                    "to_rn2",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    self.HOME,
                    "to_hn0",
                    frozenset(
                        (
                            ChiChannelKind.REQ,
                            ChiChannelKind.RSP,
                            *(
                                (ChiChannelKind.DAT,)
                                if uses_dirty_data
                                else ()
                            ),
                        )
                    ),
                ),
            ),
            queue_capacity=1,
        )

        port_binding = ChiParticipantPortBinding
        bindings = {
            "rn0": ChiParticipantBinding(
                "rn0",
                duts["rn0"],
                requester,
                (
                    port_binding(
                        duts["rn0"].port("tx_req_rsp"),
                        frozenset(
                            (ChiChannelKind.REQ, ChiChannelKind.RSP)
                        ),
                    ),
                    port_binding(
                        duts["rn0"].port("rx_dat"),
                        frozenset((ChiChannelKind.DAT,)),
                    ),
                ),
                frozenset((self.REQUESTER,)),
            ),
            "hn0": ChiParticipantBinding(
                "hn0",
                duts["hn0"],
                home,
                (
                    port_binding(
                        duts["hn0"].port("rx_req_rsp"),
                        frozenset(
                            (
                                ChiChannelKind.REQ,
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    port_binding(
                        duts["hn0"].port("tx_dat_snp"),
                        frozenset(
                            (ChiChannelKind.DAT, ChiChannelKind.SNP)
                        ),
                    ),
                ),
                frozenset((self.HOME,)),
            ),
        }
        for name, node_id in (
            ("rn1", self.FIRST_SNOOPEE),
            ("rn2", self.SECOND_SNOOPEE),
        ):
            bindings[name] = ChiParticipantBinding(
                name,
                duts[name],
                snoopees[name],
                (
                    port_binding(
                        duts[name].port("rx_snp"),
                        frozenset((ChiChannelKind.SNP,)),
                    ),
                    port_binding(
                        duts[name].port("tx_rsp"),
                        frozenset(
                            (
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                ),
                frozenset((node_id,)),
            )
        bindings["xp0"] = ChiParticipantBinding(
            "xp0",
            duts["xp0"],
            router,
            tuple(
                port_binding(
                    duts["xp0"].port(name),
                    channels,
                )
                for name, channels in (
                    (
                        "from_rn0",
                        frozenset(
                            (ChiChannelKind.REQ, ChiChannelKind.RSP)
                        ),
                    ),
                    (
                        "from_rn1",
                        frozenset(
                            (
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    (
                        "from_rn2",
                        frozenset(
                            (
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    (
                        "from_hn0",
                        frozenset(
                            (ChiChannelKind.DAT, ChiChannelKind.SNP)
                        ),
                    ),
                    ("to_rn0", frozenset((ChiChannelKind.DAT,))),
                    ("to_rn1", frozenset((ChiChannelKind.SNP,))),
                    ("to_rn2", frozenset((ChiChannelKind.SNP,))),
                    (
                        "to_hn0",
                        frozenset(
                            (
                                ChiChannelKind.REQ,
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                )
            ),
        )

        contract = ChiFeatureContract(
            {"requester": "rn0"},
            frozenset(
                CHI_MESI_NO_SD_REQUIRED_FEATURES
                if mesi
                else (
                    (
                        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER
                        if dirty
                        else CHI_FEATURE_CLEAN_READ_UNIQUE
                    ),
                )
            ),
        )
        capabilities = (
            ChiParticipantCapability(
                "rn0",
                (
                    (
                        CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES
                    )
                    if mesi
                    else (
                        CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES
                        if dirty
                        else CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                    )
                ),
            ),
            ChiParticipantCapability(
                "hn0",
                (
                    (
                        CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_HOME_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES
                    )
                    if mesi
                    else (
                        CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_HOME_CAPABILITIES
                        if dirty
                        else CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                    )
                ),
            ),
            ChiParticipantCapability(
                "rn1",
                (
                    (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES
                    )
                    if mesi
                    else (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        if dirty
                        else CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                    )
                ),
            ),
            ChiParticipantCapability(
                "rn2",
                (
                    (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES
                    )
                    if mesi
                    else (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        if dirty
                        else CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                    )
                ),
            ),
        )
        return resolve_chi_system(
            system,
            facets=(
                *(
                    ChiBehaviorFacet.from_binding(
                        bindings[name],
                        ChiFacetKind.TRANSACTION,
                    )
                    for name in ("rn0", "rn1", "rn2", "hn0")
                ),
                ChiBehaviorFacet.from_binding(
                    bindings["xp0"],
                    ChiFacetKind.FORWARDING,
                ),
            ),
            feature_contract=contract,
            authority_contract=ChiCoherenceAuthorityContract(
                authorities=(
                    ChiHomeAuthority(
                        home_address_claim,
                        "hn0",
                        "coherent_agents",
                    ),
                ),
                domains=(
                    ChiCoherenceDomain(
                        "coherent_agents",
                        frozenset(("rn0", "rn1", "rn2")),
                    ),
                ),
            ),
            feature_address_claim=home_address_claim,
            participant_capabilities=capabilities,
            system_capabilities=frozenset(
                (
                    *(
                        (
                            CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                            CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
                            CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE,
                        )
                        if mesi
                        else (
                            (
                                CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                                CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
                            )
                            if dirty
                            else (
                                CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                            )
                        )
                    ),
                )
            ),
            transmitter_capacity_by_connection={"hn0_to_xp": 1},
        )

    @staticmethod
    def packets_from(transition) -> tuple:
        return tuple(
            event.packet
            for event in transition.emissions
            if getattr(event, "packet", None) is not None
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_read_unique_closes_through_one_xp_without_losing_fanout(
        self,
    ) -> None:
        resolved = self.build_resolved()
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()

        self.assertIsInstance(state, ChiCoherenceNetworkState)
        self.assertIs(session.network, resolved.network)
        self.assertEqual(0, state.scheduler_cursor)
        self.assertEqual(0, state.committed_microsteps)

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(
                    transaction_id=0x12,
                    address=self.ADDRESS,
                ),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        maximum_pending_egress = len(state.pending_egress)
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            maximum_pending_egress = max(
                maximum_pending_egress,
                len(state.pending_egress),
            )
            for packet in self.packets_from(advanced):
                packet_by_identity[id(packet)] = packet
        else:
            self.fail("clean ReadUnique did not quiesce within 1024 microsteps")

        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadUniqueMessage])
        self.assertEqual(2, message_counts[ChiSnpUniqueMessage])
        self.assertEqual(2, message_counts[ChiSnpRespMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(7, len(packets))

        snoops = tuple(
            packet
            for packet in packets
            if isinstance(packet.message, ChiSnpUniqueMessage)
        )
        self.assertEqual(
            {self.FIRST_SNOOPEE, self.SECOND_SNOOPEE},
            {packet.target_id for packet in snoops},
        )
        self.assertGreaterEqual(maximum_pending_egress, 2)

        router_state = state.network.routers["xp0"]
        self.assertEqual(7, router_state.accepted_count)
        self.assertEqual(7, router_state.forwarded_count)
        self.assertFalse(state.pending_egress)
        self.assertTrue(session.network.is_quiescent(state.network))
        self.assertTrue(session.coherence.is_quiescent(state.coherence))
        self.assertTrue(session.is_quiescent(state))

        requester = state.coherence.request_nodes[self.REQUESTER]
        first = state.coherence.request_nodes[self.FIRST_SNOOPEE]
        second = state.coherence.request_nodes[self.SECOND_SNOOPEE]
        self.assertEqual(
            ChiCacheState.UC,
            requester.lines[self.ADDRESS].state,
        )
        self.assertEqual(
            ChiCacheState.I,
            first.lines[self.ADDRESS].state,
        )
        self.assertEqual(
            ChiCacheState.I,
            second.lines[self.ADDRESS].state,
        )
        directory = state.coherence.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, directory.unique_owner)
        self.assertFalse(directory.sharers)

    def test_dirty_unique_responsibility_crosses_the_same_xp(self) -> None:
        resolved = self.build_resolved(dirty=True)
        self.assertTrue(resolved.is_closed)
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        dirty_data = (1 << 420) | 0xD177

        dirtied = self.apply(
            session,
            state,
            ChiWriteUniqueCacheLine(
                self.FIRST_SNOOPEE,
                self.ADDRESS,
                dirty_data,
            ),
        )
        state = dirtied.state
        self.assertIs(
            ChiCacheState.UD,
            state.coherence.request_nodes[self.FIRST_SNOOPEE]
            .lines[self.ADDRESS]
            .state,
        )

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(0x13, self.ADDRESS),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            for packet in self.packets_from(advanced):
                packet_by_identity[id(packet)] = packet
        else:
            self.fail(
                "dirty ReadUnique did not quiesce within 1024 microsteps"
            )

        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadUniqueMessage])
        self.assertEqual(1, message_counts[ChiSnpUniqueMessage])
        self.assertEqual(1, message_counts[ChiSnpRespDataMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(5, len(packets))

        snoop_data = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpRespDataMessage)
        )
        completion = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiCompDataMessage)
        )
        self.assertEqual(ChiRespCode.I_PD, snoop_data.response)
        self.assertEqual(dirty_data, snoop_data.data)
        self.assertEqual(ChiRespCode.UD_PD, completion.response)
        self.assertEqual(dirty_data, completion.data)

        final_line = state.coherence.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        self.assertIs(ChiCacheState.UD, final_line.state)
        self.assertEqual(dirty_data, final_line.data)
        entry = state.coherence.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertEqual(self.DATA, entry.data)

    def test_mesi_dirty_owner_downgrades_to_two_clean_sharers(self) -> None:
        resolved = self.build_resolved(mesi=True)
        self.assertTrue(resolved.is_closed)
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        dirty_data = (1 << 420) | 0xD175

        dirtied = self.apply(
            session,
            state,
            ChiWriteUniqueCacheLine(
                self.FIRST_SNOOPEE,
                self.ADDRESS,
                dirty_data,
            ),
        )
        state = dirtied.state
        self.assertIs(
            ChiCacheState.UD,
            state.coherence.request_nodes[self.FIRST_SNOOPEE]
            .lines[self.ADDRESS]
            .state,
        )

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadNotSharedDirtyMessage(0x14, self.ADDRESS),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        observed_pending_dirty_responsibility = False
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            emitted_packets = self.packets_from(advanced)
            for packet in emitted_packets:
                packet_by_identity[id(packet)] = packet
            if any(
                isinstance(packet.message, ChiCompDataMessage)
                for packet in emitted_packets
            ):
                pending = tuple(state.coherence.home.pending.values())
                self.assertEqual(1, len(pending))
                self.assertIsNotNone(pending[0].dirty_result)
                assert pending[0].dirty_result is not None
                self.assertEqual(
                    dirty_data,
                    pending[0].dirty_result.data,
                )
                self.assertEqual(
                    self.DATA,
                    state.coherence.home.directory[self.ADDRESS].data,
                )
                observed_pending_dirty_responsibility = True
        else:
            self.fail(
                "MESI ReadNotSharedDirty did not quiesce within 1024 "
                "microsteps"
            )

        self.assertTrue(observed_pending_dirty_responsibility)
        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadNotSharedDirtyMessage])
        self.assertEqual(1, message_counts[ChiSnpNotSharedDirtyMessage])
        self.assertEqual(1, message_counts[ChiSnpRespDataMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(5, len(packets))

        snoop = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpNotSharedDirtyMessage)
        )
        snoop_data = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpRespDataMessage)
        )
        completion = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiCompDataMessage)
        )
        self.assertTrue(snoop.do_not_go_to_shared_dirty)
        self.assertEqual(ChiRespCode.SC_PD, snoop_data.response)
        self.assertEqual(dirty_data, snoop_data.data)
        self.assertEqual(ChiRespCode.SC, completion.response)
        self.assertEqual(dirty_data, completion.data)

        requester_line = state.coherence.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        former_owner_line = state.coherence.request_nodes[
            self.FIRST_SNOOPEE
        ].lines[self.ADDRESS]
        self.assertIs(ChiCacheState.SC, requester_line.state)
        self.assertIs(ChiCacheState.SC, former_owner_line.state)
        self.assertEqual(dirty_data, requester_line.data)
        self.assertEqual(dirty_data, former_owner_line.data)

        entry = state.coherence.home.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertEqual(
            frozenset((self.REQUESTER, self.FIRST_SNOOPEE)),
            entry.sharers,
        )
        self.assertEqual(dirty_data, entry.data)

    def test_full_line_coherence_rejects_a_narrow_dat_path(self) -> None:
        resolved = self.build_resolved(data_width=256)

        with self.assertRaisesRegex(ValueError, "full 512-bit cache line"):
            ChiCoherenceNetworkSession.from_resolved(resolved)


if __name__ == "__main__":
    unittest.main()
