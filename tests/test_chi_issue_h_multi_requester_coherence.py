from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.observation import (
    chi_network_flow_participants,
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
    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiCleanUniqueMessage,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiAdvanceCoherenceNetwork,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCleanUnique,
    ChiSubmitWriteBackFull,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_BUILTIN_FEATURE_CATALOG,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_FEATURE_MAKE_UNIQUE,
    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
    CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
    ChiRoleCardinality,
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
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHMultiRequesterCoherenceTest(unittest.TestCase):
    OLD_OWNER = 0x07
    CONTENDER = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    STALE_DATA = 0x1122
    DIRTY_DATA = (1 << 400) | 0xD177

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

    def build_resolved(self, *, multiple: bool):
        builder = SystemProtocolBuilder("chi_multi_requester_via_xp")
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
        rn_tx_channels = frozenset(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            )
        )
        rn_rx_channels = frozenset(
            (ChiChannelKind.RSP, ChiChannelKind.SNP)
        )
        home_tx_channels = frozenset(
            (ChiChannelKind.RSP, ChiChannelKind.SNP)
        )
        home_rx_channels = frozenset(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            )
        )
        connections = (
            *(
                (
                    f"{name}_to_xp",
                    VirtualDutPortRef(name, "tx_to_xp"),
                    VirtualDutPortRef("xp0", f"from_{name}"),
                    rn_tx_channels,
                )
                for name in ("rn0", "rn1")
            ),
            (
                "hn0_to_xp",
                VirtualDutPortRef("hn0", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_hn0"),
                home_tx_channels,
            ),
            *(
                (
                    f"xp_to_{name}",
                    VirtualDutPortRef("xp0", f"to_{name}"),
                    VirtualDutPortRef(name, "rx_from_xp"),
                    rn_rx_channels,
                )
                for name in ("rn0", "rn1")
            ),
            (
                "xp_to_hn0",
                VirtualDutPortRef("xp0", "to_hn0"),
                VirtualDutPortRef("hn0", "rx_from_xp"),
                home_rx_channels,
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
        claim_name = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                claim_name,
                VirtualDutPortRef("hn0", "rx_from_xp"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        rn0 = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.OLD_OWNER,
            self.HOME,
            port_channels={
                "tx_to_xp": rn_tx_channels,
                "rx_from_xp": rn_rx_channels,
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UD,
                    self.DIRTY_DATA,
                ),
            ),
            participant_name="old_owner",
            binding_name="rn0",
        )
        rn1 = bind_chi_issue_h_cache_lines(
            duts["rn1"],
            self.CONTENDER,
            self.HOME,
            port_channels={
                "tx_to_xp": rn_tx_channels,
                "rx_from_xp": rn_rx_channels,
            },
            participant_name="contender",
            binding_name="rn1",
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.STALE_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.OLD_OWNER,
                ),
            ),
            allow_dirty_data_transfer=True,
        )
        home_binding = ChiParticipantBinding(
            "hn0",
            duts["hn0"],
            home,
            (
                ChiParticipantPortBinding(
                    duts["hn0"].port("tx_to_xp"),
                    home_tx_channels,
                ),
                ChiParticipantPortBinding(
                    duts["hn0"].port("rx_from_xp"),
                    home_rx_channels,
                ),
            ),
            frozenset((self.HOME,)),
        )
        router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=("from_rn0", "from_rn1", "from_hn0"),
            egress_ports=("to_rn0", "to_rn1", "to_hn0"),
            routes=(
                ChiExactNodeRoute(
                    self.OLD_OWNER,
                    "to_rn0",
                    rn_rx_channels,
                ),
                ChiExactNodeRoute(
                    self.CONTENDER,
                    "to_rn1",
                    rn_rx_channels,
                ),
                ChiExactNodeRoute(
                    self.HOME,
                    "to_hn0",
                    home_rx_channels,
                ),
            ),
            queue_capacity=1,
        )
        channel_by_router_port = {
            "from_rn0": rn_tx_channels,
            "from_rn1": rn_tx_channels,
            "from_hn0": home_tx_channels,
            "to_rn0": rn_rx_channels,
            "to_rn1": rn_rx_channels,
            "to_hn0": home_rx_channels,
        }
        router_binding = ChiParticipantBinding(
            "xp0",
            duts["xp0"],
            router,
            tuple(
                ChiParticipantPortBinding(
                    duts["xp0"].port(name),
                    channels,
                )
                for name, channels in channel_by_router_port.items()
            ),
        )
        requester_capabilities = (
            CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES
            | CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES
        )
        snoopee_capabilities = (
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
            | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES
        )
        requester_roles = (
            {}
            if multiple
            else {"requester": "rn0"}
        )
        requester_role_sets = (
            {"requester": frozenset(("rn0", "rn1"))}
            if multiple
            else {}
        )
        return resolve_chi_system(
            system,
            facets=(
                rn0.facets.facets[0],
                rn1.facets.facets[0],
                ChiBehaviorFacet.from_binding(
                    home_binding,
                    ChiFacetKind.TRANSACTION,
                ),
                ChiBehaviorFacet.from_binding(
                    router_binding,
                    ChiFacetKind.FORWARDING,
                ),
            ),
            feature_contract=ChiFeatureContract(
                requester_roles,
                frozenset(
                    (
                        CHI_FEATURE_DIRTY_WRITEBACK,
                        CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                    )
                ),
                requester_role_sets,
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
                    requester_capabilities | snoopee_capabilities,
                ),
                ChiParticipantCapability(
                    "rn1",
                    requester_capabilities | snoopee_capabilities,
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES
                    | CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
                    | CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
                ),
            ),
            system_capabilities=frozenset(
                (
                    CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
                    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
                    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
                )
            ),
        )

    def assert_accepted(self, transition):
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_multi_requester_obligations_close_through_xp(self) -> None:
        resolved = self.build_resolved(multiple=True)

        self.assertTrue(resolved.is_closed)
        self.assertEqual(
            ("rn0", "rn1"),
            resolved.feature_contract.role_members("requester"),
        )
        self.assertEqual(
            ("rn0", "rn1"),
            resolved.feature_contract.role_members("snoopee"),
        )
        writeback = resolved.capabilities.require(
            CHI_FEATURE_DIRTY_WRITEBACK
        )
        self.assertEqual(
            ("rn0_to_xp", "xp_to_hn0"),
            writeback.flows[
                "writeback_request[rn0->hn0]"
            ].connections,
        )
        self.assertEqual(
            ("hn0_to_xp", "xp_to_rn1"),
            writeback.flows[
                "writeback_dbid_response[hn0->rn1]"
            ].connections,
        )
        self.assertEqual(
            ("rn1_to_xp", "xp_to_hn0"),
            writeback.flows[
                "writeback_copyback_data[rn1->hn0]"
            ].connections,
        )
        clean_unique = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        self.assertEqual(
            ("hn0_to_xp", "xp_to_rn0"),
            clean_unique.flows[
                "clean_unique_snoop[hn0->rn0]"
            ].connections,
        )
        self.assertEqual(
            ("hn0_to_xp", "xp_to_rn1"),
            clean_unique.flows[
                "clean_unique_snoop[hn0->rn1]"
            ].connections,
        )

    def test_builtin_multi_requester_scope_is_narrow(self) -> None:
        def requester_cardinality(feature):
            definition = CHI_BUILTIN_FEATURE_CATALOG.definitions[feature]
            return next(
                requirement.cardinality
                for requirement in definition.roles
                if requirement.role == "requester"
            )

        self.assertIs(
            ChiRoleCardinality.FINITE_SET,
            requester_cardinality(CHI_FEATURE_DIRTY_WRITEBACK),
        )
        self.assertIs(
            ChiRoleCardinality.FINITE_SET,
            requester_cardinality(
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            ),
        )
        self.assertIs(
            ChiRoleCardinality.SINGLE,
            requester_cardinality(CHI_FEATURE_MAKE_UNIQUE),
        )

    def test_resolved_sessions_collect_both_requesters_and_snoopee_union(
        self,
    ) -> None:
        resolved = self.build_resolved(multiple=True)
        participant_session = ChiCoherenceSession.from_resolved(resolved)

        self.assertEqual(
            frozenset((self.OLD_OWNER, self.CONTENDER)),
            participant_session.requester_node_ids,
        )
        self.assertEqual(
            frozenset((self.OLD_OWNER, self.CONTENDER)),
            participant_session.snoopee_node_ids,
        )
        writeback = self.assert_accepted(
            participant_session.step(
                participant_session.initial_state(),
                ChiSubmitWriteBackFull(
                    self.OLD_OWNER,
                    ChiWriteBackFullMessage(0x31, self.ADDRESS),
                ),
            )
        )
        self.assert_accepted(
            participant_session.step(
                writeback.state,
                ChiSubmitCleanUnique(
                    self.CONTENDER,
                    ChiCleanUniqueMessage(0x32, self.ADDRESS),
                ),
            )
        )

        network_session = ChiCoherenceNetworkSession.from_resolved(resolved)
        self.assertEqual(
            {"rn0", "rn1", "hn0"},
            set(network_session.binding_by_name),
        )
        participants = chi_network_flow_participants(network_session)
        self.assertEqual(
            ("rn0", "rn1", "hn0"),
            tuple(item.ref for item in participants),
        )
        self.assertEqual(
            ("requester/snoopee", "requester/snoopee", "home"),
            tuple(item.role for item in participants),
        )

    def test_named_scheduler_candidate_is_selective_and_public(self) -> None:
        session = ChiCoherenceNetworkSession.from_resolved(
            self.build_resolved(multiple=True)
        )
        initial = session.initial_state()
        issued = self.assert_accepted(
            session.step(
                initial,
                ChiSubmitWriteBackFull(
                    self.OLD_OWNER,
                    ChiWriteBackFullMessage(0x31, self.ADDRESS),
                ),
            )
        )
        self.assertIn("egress.enqueue", session.scheduler_candidates)
        self.assertIn(
            "tick.rn1_to_xp",
            session.scheduler_candidates,
        )
        with self.assertRaises(AttributeError):
            session.scheduler_candidates = ()  # type: ignore[misc]
        unavailable = session.step(
            issued.state,
            ChiAdvanceCoherenceNetwork(
                candidate="capture.rn1_to_xp.req"
            ),
        )
        self.assertIsNotNone(unavailable.blocked)
        self.assertIs(issued.state, unavailable.state)

        enqueued_writeback = self.assert_accepted(
            session.step(
                issued.state,
                ChiAdvanceCoherenceNetwork(candidate="egress.enqueue"),
            )
        )
        clean_unique = self.assert_accepted(
            session.step(
                enqueued_writeback.state,
                ChiSubmitCleanUnique(
                    self.CONTENDER,
                    ChiCleanUniqueMessage(0x32, self.ADDRESS),
                ),
            )
        )
        enqueued_clean_unique = self.assert_accepted(
            session.step(
                clean_unique.state,
                ChiAdvanceCoherenceNetwork(candidate="egress.enqueue"),
            )
        )
        rn1_tick = self.assert_accepted(
            session.step(
                enqueued_clean_unique.state,
                ChiAdvanceCoherenceNetwork(candidate="tick.rn1_to_xp"),
            )
        )
        self.assertEqual(
            enqueued_clean_unique.state.network.paths["rn0_to_xp"],
            rn1_tick.state.network.paths["rn0_to_xp"],
        )
        self.assertEqual(
            ChiCoherenceNetworkEventKind.NETWORK,
            rn1_tick.emissions[0].kind,
        )
        self.assertEqual(
            "rn1_to_xp",
            rn1_tick.emissions[0].connection,
        )
        with self.assertRaisesRegex(
            ValueError, "unknown CHI scheduler candidate"
        ):
            session.step(
                rn1_tick.state,
                ChiAdvanceCoherenceNetwork(candidate="tick.unknown"),
            )
        with self.assertRaisesRegex(TypeError, "must be a string"):
            ChiAdvanceCoherenceNetwork(candidate=1)  # type: ignore[arg-type]

    def test_scalar_requester_keeps_singleton_authority(self) -> None:
        resolved = self.build_resolved(multiple=False)
        session = ChiCoherenceSession.from_resolved(resolved)

        self.assertEqual(
            frozenset((self.OLD_OWNER,)),
            session.requester_node_ids,
        )
        self.assertEqual(
            frozenset((self.CONTENDER,)),
            session.snoopee_node_ids,
        )
        rejected = session.step(
            session.initial_state(),
            ChiSubmitCleanUnique(
                self.CONTENDER,
                ChiCleanUniqueMessage(0x32, self.ADDRESS),
            ),
        )
        self.assertIsNotNone(rejected.fault)
        assert rejected.fault is not None
        self.assertTrue(
            rejected.fault.rule.endswith("requester_authority")
        )


if __name__ == "__main__":
    unittest.main()
