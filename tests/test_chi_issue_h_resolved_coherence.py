from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    build_chi_cache_participant_fixture,
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
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
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
from protocol_model.system import SystemProtocolBuilder, VirtualDutPortRef
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

    def build_resolved(self, *, compound_requester: bool = False):
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
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        requester = build_chi_cache_participant_fixture(
            "requester",
            self.REQUESTER,
            self.HOME,
        )
        peers = {
            "rn1": build_chi_cache_participant_fixture(
                "peer1",
                self.FIRST_PEER,
                self.HOME,
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.SC,
                        self.DATA,
                    ),
                ),
            ),
            "rn2": build_chi_cache_participant_fixture(
                "peer2",
                self.SECOND_PEER,
                self.HOME,
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.SC,
                        self.DATA,
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
                    sharers=frozenset(
                        (self.FIRST_PEER, self.SECOND_PEER)
                    ),
                ),
            ),
        )
        item = ChiParticipantPortBinding
        bindings = {
            "rn0": ChiParticipantBinding(
                "rn0",
                duts["rn0"],
                requester,
                (
                    item(
                        duts["rn0"].port("tx_req_ack"),
                        frozenset(
                            (ChiChannelKind.REQ, ChiChannelKind.RSP)
                        ),
                    ),
                    item(
                        duts["rn0"].port("rx_dat"),
                        frozenset((ChiChannelKind.DAT,)),
                    ),
                ),
                frozenset(
                    (self.REQUESTER, 0x0A)
                    if compound_requester
                    else (self.REQUESTER,)
                ),
            ),
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
        for index, (name, node) in enumerate(peers.items(), start=1):
            bindings[name] = ChiParticipantBinding(
                name,
                duts[name],
                node,
                (
                    item(
                        duts[name].port("rx_snp"),
                        frozenset((ChiChannelKind.SNP,)),
                    ),
                    item(
                        duts[name].port("tx_rsp"),
                        frozenset((ChiChannelKind.RSP,)),
                    ),
                ),
                frozenset(
                    (
                        self.FIRST_PEER
                        if index == 1
                        else self.SECOND_PEER,
                    )
                ),
            )

        contract = ChiFeatureContract(
            {"requester": "rn0", "home": "hn0"},
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
            role_sets={"snoopee": frozenset(("rn1", "rn2"))},
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
            facets=tuple(
                ChiBehaviorFacet.from_binding(
                    binding,
                    ChiFacetKind.TRANSACTION,
                )
                for binding in bindings.values()
            ),
            feature_contract=contract,
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

    def test_factory_rejects_compound_binding_without_runtime_identity(self) -> None:
        resolved, _, _, _ = self.build_resolved(compound_requester=True)

        with self.assertRaisesRegex(
            ValueError,
            "offer exactly its component NodeID",
        ):
            ChiCoherenceSession.from_resolved(resolved)


if __name__ == "__main__":
    unittest.main()
