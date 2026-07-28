from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiNetworkPacket,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCoherentRead,
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
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHResolvedCoherenceTest(unittest.TestCase):
    REQUESTER = 0x07
    FIRST_PEER = 0x08
    SECOND_PEER = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC0DE

    @staticmethod
    def port(name: str, direction: TransportDirection) -> TransportPort:
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
        compound_requester: bool = False,
        domain_members: frozenset[str] = frozenset(
            ("rn0", "rn1", "rn2")
        ),
        extra_directory_holder: int | None = None,
        bind_manual_authority_roles: bool = False,
    ):
        builder = SystemProtocolBuilder("chi_resolved_clean_unique")
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_req_ack": self.port(
                        "tx_req_ack",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_dat": self.port(
                        "rx_dat",
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
                    "tx_dat": self.port(
                        "tx_dat",
                        TransportDirection.TRANSMIT,
                    ),
                    "tx_snp_1": self.port(
                        "tx_snp_1",
                        TransportDirection.TRANSMIT,
                    ),
                    "tx_snp_2": self.port(
                        "tx_snp_2",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_rsp_1": self.port(
                        "rx_rsp_1",
                        TransportDirection.RECEIVE,
                    ),
                    "rx_rsp_2": self.port(
                        "rx_rsp_2",
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

        connections = (
            (
                "request_ack",
                VirtualDutPortRef("rn0", "tx_req_ack"),
                VirtualDutPortRef("hn0", "rx_req_ack"),
                frozenset((ChiChannelKind.REQ, ChiChannelKind.RSP)),
            ),
            (
                "completion_data",
                VirtualDutPortRef("hn0", "tx_dat"),
                VirtualDutPortRef("rn0", "rx_dat"),
                frozenset((ChiChannelKind.DAT,)),
            ),
            (
                "snoop_1",
                VirtualDutPortRef("hn0", "tx_snp_1"),
                VirtualDutPortRef("rn1", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "snoop_2",
                VirtualDutPortRef("hn0", "tx_snp_2"),
                VirtualDutPortRef("rn2", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "snoop_response_1",
                VirtualDutPortRef("rn1", "tx_rsp"),
                VirtualDutPortRef("hn0", "rx_rsp_1"),
                frozenset((ChiChannelKind.RSP,)),
            ),
            (
                "snoop_response_2",
                VirtualDutPortRef("rn2", "tx_rsp"),
                VirtualDutPortRef("hn0", "rx_rsp_2"),
                frozenset((ChiChannelKind.RSP,)),
            ),
        )
        for name, transmitter, receiver, channels in connections:
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=self.link_profile(name, channels),
            )
        home_address_claim = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                home_address_claim,
                VirtualDutPortRef("hn0", "rx_req_ack"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        requester_assembly = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.REQUESTER,
            self.HOME,
            port_channels={
                "tx_req_ack": frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
                "rx_dat": frozenset((ChiChannelKind.DAT,)),
            },
            participant_name="requester",
            binding_name="rn0",
        )
        peer_assemblies = {
            "rn1": bind_chi_issue_h_cache_lines(
                duts["rn1"],
                self.FIRST_PEER,
                self.HOME,
                port_channels={
                    "rx_snp": frozenset((ChiChannelKind.SNP,)),
                    "tx_rsp": frozenset((ChiChannelKind.RSP,)),
                },
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.SC,
                        self.DATA,
                    ),
                ),
                participant_name="peer1",
                binding_name="rn1",
            ),
            "rn2": bind_chi_issue_h_cache_lines(
                duts["rn2"],
                self.SECOND_PEER,
                self.HOME,
                port_channels={
                    "rx_snp": frozenset((ChiChannelKind.SNP,)),
                    "tx_rsp": frozenset((ChiChannelKind.RSP,)),
                },
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.SC,
                        self.DATA,
                    ),
                ),
                participant_name="peer2",
                binding_name="rn2",
            ),
        }
        requester = requester_assembly.participant
        peers = {
            name: assembly.participant
            for name, assembly in peer_assemblies.items()
        }
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=frozenset(
                        (
                            self.FIRST_PEER,
                            self.SECOND_PEER,
                            *(
                                ()
                                if extra_directory_holder is None
                                else (extra_directory_holder,)
                            ),
                        )
                    ),
                ),
            ),
        )
        item = ChiParticipantPortBinding
        requester_binding = requester_assembly.binding
        if compound_requester:
            requester_binding = ChiParticipantBinding(
                requester_binding.name,
                requester_binding.dut,
                requester_binding.component,
                requester_binding.ports,
                frozenset((self.REQUESTER, 0x0A)),
            )
        bindings = {
            "rn0": requester_binding,
            "hn0": ChiParticipantBinding(
                "hn0",
                duts["hn0"],
                home,
                (
                    item(
                        duts["hn0"].port("rx_req_ack"),
                        frozenset(
                            (ChiChannelKind.REQ, ChiChannelKind.RSP)
                        ),
                    ),
                    item(
                        duts["hn0"].port("tx_dat"),
                        frozenset((ChiChannelKind.DAT,)),
                    ),
                    item(
                        duts["hn0"].port("tx_snp_1"),
                        frozenset((ChiChannelKind.SNP,)),
                    ),
                    item(
                        duts["hn0"].port("tx_snp_2"),
                        frozenset((ChiChannelKind.SNP,)),
                    ),
                    item(
                        duts["hn0"].port("rx_rsp_1"),
                        frozenset((ChiChannelKind.RSP,)),
                    ),
                    item(
                        duts["hn0"].port("rx_rsp_2"),
                        frozenset((ChiChannelKind.RSP,)),
                    ),
                ),
                frozenset((self.HOME,)),
            ),
        }
        bindings.update(
            {
                name: assembly.binding
                for name, assembly in peer_assemblies.items()
            }
        )

        contract = ChiFeatureContract(
            (
                {"requester": "rn0", "home": "hn0"}
                if bind_manual_authority_roles
                else {"requester": "rn0"}
            ),
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
            role_sets=(
                {"snoopee": frozenset(("rn1", "rn2"))}
                if bind_manual_authority_roles
                else {}
            ),
        )
        capabilities = (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "rn1",
                CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "rn2",
                CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
            ),
        )
        resolved = resolve_chi_system(
            system,
            facets=(
                (
                    ChiBehaviorFacet.from_binding(
                        requester_binding,
                        ChiFacetKind.TRANSACTION,
                    )
                    if compound_requester
                    else requester_assembly.facets.facets[0]
                ),
                ChiBehaviorFacet.from_binding(
                    bindings["hn0"],
                    ChiFacetKind.TRANSACTION,
                ),
                *(
                    assembly.facets.facets[0]
                    for assembly in peer_assemblies.values()
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
                        domain_members,
                    ),
                ),
            ),
            feature_address_claim=home_address_claim,
            participant_capabilities=capabilities,
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
            ),
            target_node_id_by_participant=(
                {"rn0": self.REQUESTER}
                if compound_requester
                else None
            ),
        )
        return resolved, requester, home, peers

    def test_from_resolved_binds_exact_registry_and_feature_authority(
        self,
    ) -> None:
        resolved, requester, home, peers = self.build_resolved()

        session = ChiCoherenceSession.from_resolved(resolved)

        self.assertTrue(resolved.is_closed)
        self.assertEqual(
            ("hn0",),
            resolved.feature_contract.role_members("home"),
        )
        self.assertEqual(
            ("rn1", "rn2"),
            resolved.feature_contract.role_members("snoopee"),
        )
        self.assertEqual(
            "hn0",
            resolved.authority_plan.authority_for_address(
                self.ADDRESS,
                64,
            ).home,
        )
        self.assertIs(home, session.home)
        self.assertIs(requester, session.request_nodes[self.REQUESTER])
        self.assertEqual(
            {self.REQUESTER, self.FIRST_PEER, self.SECOND_PEER},
            set(session.request_nodes),
        )
        self.assertEqual(
            frozenset((self.REQUESTER,)),
            session.requester_node_ids,
        )
        self.assertEqual(
            frozenset((self.FIRST_PEER, self.SECOND_PEER)),
            session.snoopee_node_ids,
        )
        self.assertEqual(
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
            session.enabled_features,
        )
        self.assertEqual(
            {peers["rn1"], peers["rn2"]},
            {
                session.request_nodes[self.FIRST_PEER],
                session.request_nodes[self.SECOND_PEER],
            },
        )

        request = ChiReadUniqueMessage(
            transaction_id=1,
            address=self.ADDRESS,
        )
        issued = session.step(
            session.initial_state(),
            ChiSubmitCoherentRead(self.REQUESTER, request),
        )
        self.assertIsNone(issued.fault)
        accepted = session.step(
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        self.assertIsNone(accepted.fault)
        self.assertEqual(
            {self.FIRST_PEER, self.SECOND_PEER},
            {packet.target_id for packet in accepted.emissions},
        )
        self.assertTrue(
            all(
                isinstance(packet.message, ChiSnpUniqueMessage)
                for packet in accepted.emissions
            )
        )

    def test_role_and_feature_gates_cannot_be_bypassed_by_delivery(
        self,
    ) -> None:
        resolved, _, _, _ = self.build_resolved()
        session = ChiCoherenceSession.from_resolved(resolved)
        state = session.initial_state()
        request = ChiReadUniqueMessage(
            transaction_id=2,
            address=self.ADDRESS,
        )

        peer_issue = session.step(
            state,
            ChiSubmitCoherentRead(self.FIRST_PEER, request),
        )
        self.assertIsNotNone(peer_issue.fault)
        self.assertIn("Snoopee", peer_issue.fault.reason)

        disabled_issue = session.step(
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadSharedMessage(
                    transaction_id=3,
                    address=self.ADDRESS,
                ),
            ),
        )
        self.assertIsNotNone(disabled_issue.fault)
        self.assertIn("not enabled", disabled_issue.fault.reason)

        forged_read = ChiNetworkPacket.request(
            request,
            source_id=self.FIRST_PEER,
            target_id=self.HOME,
        )
        delivered_read = session.step(
            state,
            ChiDeliverCoherencePacket(forged_read),
        )
        self.assertIsNotNone(delivered_read.fault)
        self.assertIn("not the requester", delivered_read.fault.reason)

        requester_snoop = ChiNetworkPacket.snoop(
            ChiSnpUniqueMessage(
                transaction_id=3,
                address=self.ADDRESS,
            ),
            source_id=self.HOME,
            target_id=self.REQUESTER,
        )
        delivered_snoop = session.step(
            state,
            ChiDeliverCoherencePacket(requester_snoop),
        )
        self.assertIsNotNone(delivered_snoop.fault)
        self.assertIn("not a Snoopee", delivered_snoop.fault.reason)

        disabled_snoop = ChiNetworkPacket.snoop(
            ChiSnpSharedMessage(
                transaction_id=4,
                address=self.ADDRESS,
            ),
            source_id=self.HOME,
            target_id=self.FIRST_PEER,
        )
        delivered_disabled = session.step(
            state,
            ChiDeliverCoherencePacket(disabled_snoop),
        )
        self.assertIsNotNone(delivered_disabled.fault)
        self.assertIn("not enabled", delivered_disabled.fault.reason)

    def test_resolution_rejects_compound_coherence_domain_identity(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "must resolve to exactly one NodeID",
        ):
            self.build_resolved(compound_requester=True)

    def test_resolution_rejects_parallel_manual_home_and_snoopee_facts(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "must not bind authority-derived roles",
        ):
            self.build_resolved(bind_manual_authority_roles=True)

    def test_requester_must_belong_to_the_selected_coherence_domain(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "is not a member of coherence domain",
        ):
            self.build_resolved(
                domain_members=frozenset(("rn1", "rn2"))
            )

    def test_session_rejects_directory_holder_outside_resolved_domain(
        self,
    ) -> None:
        resolved, _, _, _ = self.build_resolved(
            extra_directory_holder=0x0A
        )

        with self.assertRaisesRegex(
            ValueError,
            "outside the resolved coherence domain",
        ):
            ChiCoherenceSession.from_resolved(resolved)

    def test_resolved_session_rejects_address_outside_selected_claim(
        self,
    ) -> None:
        resolved, _, _, _ = self.build_resolved()
        session = ChiCoherenceSession.from_resolved(resolved)

        transition = session.step(
            session.initial_state(),
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(
                    transaction_id=0x12,
                    address=self.ADDRESS + 0x40,
                ),
            ),
        )

        self.assertIsNotNone(transition.fault)
        assert transition.fault is not None
        self.assertIn("address_authority", transition.fault.rule)


if __name__ == "__main__":
    unittest.main()
