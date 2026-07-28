from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.participants.capability import (
    CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
    CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
)
from protocol_model.protocols.amba.chi.issue_h.participants.coherence import (
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeDirectoryEntry,
)
from protocol_model.protocols.amba.chi.issue_h.representation.dat import (
    ChiCompDataMessage,
    ChiSnpRespDataMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.packet import (
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
)
from protocol_model.protocols.amba.chi.issue_h.representation.req import (
    ChiMakeUniqueMessage,
    ChiReadUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.response import (
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.representation.rsp import (
    ChiCompAckMessage,
    ChiCompMessage,
    ChiSnpRespMessage,
)
from protocol_model.protocols.amba.chi.issue_h.representation.snp import (
    ChiSnpMakeInvalidMessage,
    ChiSnpUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_MAKE_UNIQUE,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE,
    ChiFeatureContract,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence import (
    ChiCoherenceSession,
    ChiCoherenceState,
    ChiDeliverCoherencePacket,
    ChiSubmitCoherentRead,
    ChiSubmitMakeUnique,
)
from protocol_model.protocols.amba.chi.issue_h.system.authority import (
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiHomeAuthority,
)
from protocol_model.protocols.amba.chi.issue_h.system.coherence_network import (
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
)
from protocol_model.protocols.amba.chi.issue_h.system.progress import (
    ChiLineRelease,
)
from protocol_model.protocols.amba.chi.issue_h.system.resolved import (
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiSnpChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import Verdict
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


class ChiIssueHMakeUniqueSystemTest(unittest.TestCase):
    REQUESTER = 0x07
    PEER = 0x08
    PEER2 = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    OLD_DATA = (1 << 400) | 0x0D
    NEW_DATA = (1 << 500) | 0x4E57
    TXN_ID = 0x12
    SNOOP_ID = 0x100
    DBID = 0x200

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_fault_rule(self, transition, expected_rule: str) -> None:
        self.assertIsNotNone(transition.fault)
        self.assertEqual(
            expected_rule,
            transition.fault.rule.rsplit(".", 1)[-1],
        )

    def build_rn(
        self,
        name: str,
        node_id: int,
        state: ChiCacheState,
    ):
        return build_chi_cache_participant_fixture(
            name,
            node_id,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    state,
                    (
                        None
                        if state in (ChiCacheState.I, ChiCacheState.UCE)
                        else self.OLD_DATA
                    ),
                ),
            ),
        )

    def build_home(
        self,
        peer_state: ChiCacheState,
        *,
        allow_dirty_data_transfer: bool = False,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.OLD_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=(
                        frozenset((self.PEER,))
                        if peer_state is ChiCacheState.SD
                        else frozenset()
                    ),
                    unique_owner=(
                        self.PEER
                        if peer_state is ChiCacheState.UD
                        else None
                    ),
                    shared_dirty_owner=(
                        self.PEER
                        if peer_state is ChiCacheState.SD
                        else None
                    ),
                ),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
            allow_dirty_data_transfer=allow_dirty_data_transfer,
        )

    def build_session(
        self,
        *,
        peer_state: ChiCacheState = ChiCacheState.SD,
        enabled_features=frozenset((CHI_FEATURE_MAKE_UNIQUE,)),
        allow_dirty_data_transfer: bool = False,
    ) -> ChiCoherenceSession:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        peer = self.build_rn("peer", self.PEER, peer_state)
        return ChiCoherenceSession(
            "make_unique",
            self.build_home(
                peer_state,
                allow_dirty_data_transfer=allow_dirty_data_transfer,
            ),
            {
                self.REQUESTER: requester,
                self.PEER: peer,
            },
            enabled_features=enabled_features,
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset((self.PEER,)),
        )

    def build_no_peer_session(self) -> ChiCoherenceSession:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.OLD_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(self.ADDRESS),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
        )
        return ChiCoherenceSession(
            "make_unique_no_peer",
            home,
            {self.REQUESTER: requester},
            enabled_features=frozenset(
                (CHI_FEATURE_MAKE_UNIQUE,)
            ),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset(),
        )

    def request(self) -> ChiMakeUniqueMessage:
        return ChiMakeUniqueMessage(self.TXN_ID, self.ADDRESS)

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
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    def build_resolved(
        self,
        *,
        required_features=frozenset((CHI_FEATURE_MAKE_UNIQUE,)),
    ):
        builder = SystemProtocolBuilder("chi_make_unique_dirty_peer")
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
        for name, transmitter, receiver, channels in (
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
            (
                "snoop_response",
                VirtualDutPortRef("rn1", "tx_rsp"),
                VirtualDutPortRef("hn0", "rx_peer_rsp"),
                frozenset((ChiChannelKind.RSP,)),
            ),
        ):
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
                VirtualDutPortRef("hn0", "rx_req_ack"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts
        requester = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.REQUESTER,
            self.HOME,
            port_channels={
                "tx_req_ack": frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
                "rx_comp": frozenset((ChiChannelKind.RSP,)),
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.I,
                    None,
                ),
            ),
            participant_name="requester",
            binding_name="rn0",
        )
        peer = bind_chi_issue_h_cache_lines(
            duts["rn1"],
            self.PEER,
            self.HOME,
            port_channels={
                "tx_rsp": frozenset((ChiChannelKind.RSP,)),
                "rx_snp": frozenset((ChiChannelKind.SNP,)),
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.SD,
                    self.OLD_DATA,
                ),
            ),
            participant_name="peer",
            binding_name="rn1",
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.OLD_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=frozenset((self.PEER,)),
                    shared_dirty_owner=self.PEER,
                ),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
        )
        home_binding = ChiParticipantBinding(
            "hn0",
            duts["hn0"],
            home,
            (
                ChiParticipantPortBinding(
                    duts["hn0"].port("rx_req_ack"),
                    frozenset(
                        (ChiChannelKind.REQ, ChiChannelKind.RSP)
                    ),
                ),
                ChiParticipantPortBinding(
                    duts["hn0"].port("tx_comp"),
                    frozenset((ChiChannelKind.RSP,)),
                ),
                ChiParticipantPortBinding(
                    duts["hn0"].port("tx_snp"),
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiParticipantPortBinding(
                    duts["hn0"].port("rx_peer_rsp"),
                    frozenset((ChiChannelKind.RSP,)),
                ),
            ),
            frozenset((self.HOME,)),
        )
        return resolve_chi_system(
            system,
            facets=(
                requester.facets.facets[0],
                peer.facets.facets[0],
                ChiBehaviorFacet.from_binding(
                    home_binding,
                    ChiFacetKind.TRANSACTION,
                ),
            ),
            feature_contract=ChiFeatureContract(
                {"requester": "rn0"},
                required_features,
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
                    CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_MAKE_UNIQUE_HOME_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "rn1",
                    CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES,
                ),
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_MAKE_UNIQUE_LIFECYCLE,)
            ),
        )

    def test_peer_lifecycle_discards_dirty_data_and_commits_on_ack(
        self,
    ) -> None:
        session = self.build_session(peer_state=ChiCacheState.SD)
        state = session.initial_state()
        initial_backing = state.home.backing.line_at(self.ADDRESS)
        assert initial_backing is not None

        issued = self.apply(
            session,
            state,
            ChiSubmitMakeUnique(
                self.REQUESTER,
                self.request(),
                self.NEW_DATA,
            ),
        )
        request_packet = issued.emissions[0]
        self.assertIsInstance(
            request_packet.message,
            ChiMakeUniqueMessage,
        )

        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(request_packet),
        )
        self.assertFalse(
            accepted.state.expected_make_unique_completions
        )
        self.assertIn(self.DBID, accepted.state.home.pending)
        snoop_packet = accepted.emissions[0]
        self.assertIsInstance(
            snoop_packet.message,
            ChiSnpMakeInvalidMessage,
        )
        snoop_key = (self.PEER, self.SNOOP_ID)
        self.assertEqual(
            snoop_packet,
            accepted.state.expected_snoop_deliveries[snoop_key],
        )
        self.assertFalse(accepted.state.expected_snoop_responses)

        early_response = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiSnpRespMessage(
                        transaction_id=self.SNOOP_ID,
                        response=ChiRespCode.I,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(
            early_response,
            "snoop_response_correlation",
        )
        self.assertIs(accepted.state, early_response.state)

        with self.assertRaisesRegex(
            ValueError,
            "unresolved Home Snoop target",
        ):
            ChiCoherenceState(
                home=accepted.state.home,
                request_nodes=accepted.state.request_nodes,
            )

        early_completion = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiCompMessage(
                        transaction_id=self.TXN_ID,
                        data_buffer_id=self.DBID,
                        response=ChiRespCode.UC,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        self.assert_fault_rule(
            early_completion,
            "make_unique_completion_correlation",
        )
        self.assertIs(accepted.state, early_completion.state)

        invalidated = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        snoop_response = invalidated.emissions[0]
        self.assertIsInstance(
            snoop_response.message,
            ChiSnpRespMessage,
        )
        self.assertIs(ChiRespCode.I, snoop_response.message.response)
        self.assertNotIn(
            snoop_key,
            invalidated.state.expected_snoop_deliveries,
        )
        self.assertEqual(
            snoop_response,
            invalidated.state.expected_snoop_responses[snoop_key],
        )
        with self.assertRaisesRegex(
            ValueError,
            "unresolved Home Snoop target",
        ):
            ChiCoherenceState(
                home=invalidated.state.home,
                request_nodes=invalidated.state.request_nodes,
                expected_snoop_deliveries=(
                    invalidated.state.expected_snoop_deliveries
                ),
            )
        forged_response = session.step(
            invalidated.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiSnpRespMessage(
                        transaction_id=self.SNOOP_ID,
                        response=ChiRespCode.I,
                        trace_tag=True,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(
            forged_response,
            "snoop_response_correlation",
        )
        self.assertIs(invalidated.state, forged_response.state)
        first_replay = session.step(
            invalidated.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        self.assert_fault_rule(
            first_replay,
            "snoop_delivery_correlation",
        )
        self.assertIs(invalidated.state, first_replay.state)

        rejected_data = session.step(
            invalidated.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.data(
                    ChiSnpRespDataMessage(
                        transaction_id=self.SNOOP_ID,
                        data=self.OLD_DATA,
                        response=ChiRespCode.I,
                    ),
                    source_id=self.PEER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(
            rejected_data,
            "make_unique_snoop_data",
        )
        self.assertIs(invalidated.state, rejected_data.state)

        collected = self.apply(
            session,
            invalidated.state,
            ChiDeliverCoherencePacket(snoop_response),
        )
        completion = collected.emissions[0]
        self.assertIsInstance(completion.message, ChiCompMessage)
        self.assertEqual(
            {
                (self.REQUESTER, self.TXN_ID): completion
            },
            dict(
                collected.state.expected_make_unique_completions
            ),
        )
        self.assertIn(self.DBID, collected.state.home.pending)
        self.assertFalse(collected.state.expected_snoop_deliveries)
        self.assertFalse(collected.state.expected_snoop_responses)
        with self.assertRaisesRegex(
            ValueError,
            "expected Comp_UC",
        ):
            ChiCoherenceState(
                home=collected.state.home,
                request_nodes=collected.state.request_nodes,
            )

        post_completion_replay = session.step(
            collected.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        self.assert_fault_rule(
            post_completion_replay,
            "snoop_delivery_correlation",
        )
        self.assertIs(
            collected.state,
            post_completion_replay.state,
        )

        early_ack = session.step(
            collected.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiCompAckMessage(
                        transaction_id=self.DBID,
                    ),
                    source_id=self.REQUESTER,
                    target_id=self.HOME,
                )
            ),
        )
        self.assert_fault_rule(
            early_ack,
            "make_unique_completion_ack_sequence",
        )

        wrong_completion = session.step(
            collected.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.response(
                    ChiCompMessage(
                        transaction_id=self.TXN_ID,
                        data_buffer_id=self.DBID + 1,
                        response=ChiRespCode.UC,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        self.assert_fault_rule(
            wrong_completion,
            "make_unique_completion_correlation",
        )

        rejected_completion_data = session.step(
            collected.state,
            ChiDeliverCoherencePacket(
                ChiNetworkPacket.data(
                    ChiCompDataMessage(
                        transaction_id=self.TXN_ID,
                        data=self.OLD_DATA,
                        home_node_id=self.HOME,
                        response=ChiRespCode.UC,
                        data_buffer_id=self.DBID,
                    ),
                    source_id=self.HOME,
                    target_id=self.REQUESTER,
                )
            ),
        )
        self.assert_fault_rule(
            rejected_completion_data,
            "make_unique_completion_data",
        )

        completed = self.apply(
            session,
            collected.state,
            ChiDeliverCoherencePacket(completion),
        )
        requester_state = completed.state.request_nodes[self.REQUESTER]
        requester_line = requester_state.line_at(self.ADDRESS)
        assert requester_line is not None
        self.assertIs(ChiCacheState.UD, requester_line.state)
        self.assertEqual(self.NEW_DATA, requester_line.data)
        self.assertFalse(
            completed.state.expected_make_unique_completions
        )
        self.assertIn(self.DBID, completed.state.home.pending)
        self.assertEqual(
            self.PEER,
            completed.state.home.directory[
                self.ADDRESS
            ].shared_dirty_owner,
        )
        ack = completed.emissions[0]
        self.assertIsInstance(ack.message, ChiCompAckMessage)

        retired = self.apply(
            session,
            completed.state,
            ChiDeliverCoherencePacket(ack),
        )
        entry = retired.state.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        peer_line = retired.state.request_nodes[self.PEER].line_at(
            self.ADDRESS
        )
        assert peer_line is not None
        self.assertIs(ChiCacheState.I, peer_line.state)
        self.assertIsNone(peer_line.data)
        final_backing = retired.state.home.backing.line_at(self.ADDRESS)
        assert final_backing is not None
        self.assertEqual(initial_backing.data, final_backing.data)
        self.assertEqual(initial_backing.version, final_backing.version)
        self.assertTrue(session.is_quiescent(retired.state))

    def test_dirty_peer_topology_routes_only_req_snp_and_rsp(
        self,
    ) -> None:
        resolved = self.build_resolved()
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        initial_backing = state.coherence.home.backing.line_at(
            self.ADDRESS
        )
        assert initial_backing is not None

        issued = self.apply(
            session,
            state,
            ChiSubmitMakeUnique(
                self.REQUESTER,
                self.request(),
                self.NEW_DATA,
            ),
        )
        progress = session.project_progress(issued.state)
        requester_holders = tuple(
            held
            for held in progress.held
            if held.holder_node_id == self.REQUESTER
        )
        self.assertEqual(1, len(requester_holders))
        self.assertIs(
            ChiLineRelease.COMP,
            requester_holders[0].release_on,
        )

        run = session.run_until_quiescent(
            issued.state,
            max_steps=1024,
        )
        self.assertIs(Verdict.PASS, run.verdict)
        endpoint_events = tuple(
            event
            for event in run.emissions
            if (
                event.kind
                is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
            )
        )
        self.assertEqual(
            (
                ChiMakeUniqueMessage,
                ChiSnpMakeInvalidMessage,
                ChiSnpRespMessage,
                ChiCompMessage,
                ChiCompAckMessage,
            ),
            tuple(
                type(event.packet.message)
                for event in endpoint_events
            ),
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
        self.assertNotIn(
            ChiChannelKind.DAT,
            {
                channel
                for _source, _target, channel
                in session.route_by_packet_key
            },
        )

        final = run.final_state.coherence
        requester_line = final.request_nodes[
            self.REQUESTER
        ].line_at(self.ADDRESS)
        peer_line = final.request_nodes[self.PEER].line_at(
            self.ADDRESS
        )
        assert requester_line is not None
        assert peer_line is not None
        self.assertIs(ChiCacheState.UD, requester_line.state)
        self.assertEqual(self.NEW_DATA, requester_line.data)
        self.assertIs(ChiCacheState.I, peer_line.state)
        self.assertIsNone(peer_line.data)
        entry = final.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertIsNone(entry.shared_dirty_owner)
        final_backing = final.home.backing.line_at(self.ADDRESS)
        assert final_backing is not None
        self.assertEqual(initial_backing.data, final_backing.data)
        self.assertEqual(initial_backing.version, final_backing.version)
        self.assertFalse(final.home.pending)
        self.assertFalse(final.expected_make_unique_completions)

    def test_read_unique_cannot_substitute_make_invalid_for_exact_snp_unique(
        self,
    ) -> None:
        session = self.build_session(
            peer_state=ChiCacheState.SD,
            enabled_features=frozenset(
                (
                    CHI_FEATURE_MAKE_UNIQUE,
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                )
            ),
            allow_dirty_data_transfer=True,
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(self.TXN_ID, self.ADDRESS),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        expected_snoop = accepted.emissions[0]
        self.assertIsInstance(
            expected_snoop.message,
            ChiSnpUniqueMessage,
        )
        forged = ChiNetworkPacket.snoop(
            ChiSnpMakeInvalidMessage(
                expected_snoop.message.transaction_id,
                expected_snoop.message.address,
            ),
            source_id=expected_snoop.source_id,
            target_id=expected_snoop.target_id,
        )
        rejected = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(forged),
        )
        self.assert_fault_rule(
            rejected,
            "snoop_delivery_correlation",
        )
        self.assertIs(accepted.state, rejected.state)
        self.assertEqual(
            expected_snoop,
            rejected.state.expected_snoop_deliveries[
                (self.PEER, self.SNOOP_ID)
            ],
        )

        delivered = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(expected_snoop),
        )
        self.assertIsInstance(
            delivered.emissions[0].message,
            ChiSnpRespDataMessage,
        )
        self.assertIs(
            ChiRespCode.I_PD,
            delivered.emissions[0].message.response,
        )

    def test_two_snoopees_advance_independent_exact_phases(
        self,
    ) -> None:
        requester = self.build_rn(
            "requester",
            self.REQUESTER,
            ChiCacheState.I,
        )
        peer = self.build_rn(
            "peer",
            self.PEER,
            ChiCacheState.SD,
        )
        peer2 = self.build_rn(
            "peer2",
            self.PEER2,
            ChiCacheState.SC,
        )
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.OLD_DATA),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=frozenset((self.PEER, self.PEER2)),
                    shared_dirty_owner=self.PEER,
                ),
            ),
            initial_snoop_transaction_id=self.SNOOP_ID,
            initial_data_buffer_id=self.DBID,
        )
        session = ChiCoherenceSession(
            "make_unique_two_peers",
            home,
            {
                self.REQUESTER: requester,
                self.PEER: peer,
                self.PEER2: peer2,
            },
            enabled_features=frozenset(
                (CHI_FEATURE_MAKE_UNIQUE,)
            ),
            requester_node_ids=frozenset((self.REQUESTER,)),
            snoopee_node_ids=frozenset((self.PEER, self.PEER2)),
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitMakeUnique(
                self.REQUESTER,
                self.request(),
                self.NEW_DATA,
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        snoops = {
            packet.target_id: packet
            for packet in accepted.emissions
        }
        self.assertEqual(
            {
                (self.PEER, self.SNOOP_ID),
                (self.PEER2, self.SNOOP_ID),
            },
            set(accepted.state.expected_snoop_deliveries),
        )

        first = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(snoops[self.PEER]),
        )
        first_response = first.emissions[0]
        self.assertEqual(
            {(self.PEER2, self.SNOOP_ID)},
            set(first.state.expected_snoop_deliveries),
        )
        self.assertEqual(
            {(self.PEER, self.SNOOP_ID)},
            set(first.state.expected_snoop_responses),
        )
        first_collected = self.apply(
            session,
            first.state,
            ChiDeliverCoherencePacket(first_response),
        )
        self.assertFalse(first_collected.emissions)
        self.assertEqual(
            {(self.PEER2, self.SNOOP_ID)},
            set(first_collected.state.expected_snoop_deliveries),
        )
        self.assertFalse(
            first_collected.state.expected_snoop_responses
        )

        second = self.apply(
            session,
            first_collected.state,
            ChiDeliverCoherencePacket(snoops[self.PEER2]),
        )
        self.assertFalse(second.state.expected_snoop_deliveries)
        self.assertEqual(
            {(self.PEER2, self.SNOOP_ID)},
            set(second.state.expected_snoop_responses),
        )
        completed_snoops = self.apply(
            session,
            second.state,
            ChiDeliverCoherencePacket(second.emissions[0]),
        )
        self.assertFalse(
            completed_snoops.state.expected_snoop_responses
        )
        completion = completed_snoops.emissions[0]
        requester_completed = self.apply(
            session,
            completed_snoops.state,
            ChiDeliverCoherencePacket(completion),
        )
        retired = self.apply(
            session,
            requester_completed.state,
            ChiDeliverCoherencePacket(
                requester_completed.emissions[0]
            ),
        )
        self.assertTrue(session.is_quiescent(retired.state))
        self.assertEqual(
            self.REQUESTER,
            retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )

    def test_no_peer_fast_path_records_the_direct_home_completion(
        self,
    ) -> None:
        session = self.build_no_peer_session()
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitMakeUnique(
                self.REQUESTER,
                self.request(),
                self.NEW_DATA,
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        self.assertEqual(1, len(accepted.emissions))
        completion = accepted.emissions[0]
        self.assertIsInstance(completion.message, ChiCompMessage)
        self.assertEqual(
            completion,
            accepted.state.expected_make_unique_completions[
                (self.REQUESTER, self.TXN_ID)
            ],
        )
        repacketized = ChiNetworkPacket.response(
            completion.message,
            source_id=self.HOME,
            target_id=self.REQUESTER,
            packet_index=1,
            packet_count=2,
        )
        rejected = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(repacketized),
        )
        self.assert_fault_rule(
            rejected,
            "make_unique_completion_correlation",
        )
        self.assertIs(accepted.state, rejected.state)

        completed = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(completion),
        )
        retired = self.apply(
            session,
            completed.state,
            ChiDeliverCoherencePacket(completed.emissions[0]),
        )
        line = retired.state.request_nodes[self.REQUESTER].line_at(
            self.ADDRESS
        )
        assert line is not None
        self.assertIs(ChiCacheState.UD, line.state)
        self.assertEqual(self.NEW_DATA, line.data)
        self.assertEqual(
            self.REQUESTER,
            retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )
        backing = retired.state.home.backing.line_at(self.ADDRESS)
        assert backing is not None
        self.assertEqual(self.OLD_DATA, backing.data)
        self.assertEqual(0, backing.version)
        self.assertTrue(session.is_quiescent(retired.state))

    def test_make_unique_and_clean_read_shared_need_a_dirty_policy(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "clean ReadShared cannot be combined",
        ):
            self.build_session(
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_SHARED,
                        CHI_FEATURE_MAKE_UNIQUE,
                    )
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "cannot combine ReadShared",
        ):
            self.build_resolved(
                required_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_SHARED,
                        CHI_FEATURE_MAKE_UNIQUE,
                    )
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "dirty Unique transfer",
        ):
            self.build_session(
                peer_state=ChiCacheState.UD,
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                    )
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "shared-dirty peer handling",
        ):
            self.build_session(
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    )
                ),
            )
        self.build_session(
            enabled_features=frozenset(
                (
                    CHI_FEATURE_MAKE_UNIQUE,
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                )
            ),
            allow_dirty_data_transfer=True,
        )
        with self.assertRaisesRegex(
            ValueError,
            "does not combine MakeUnique",
        ):
            self.build_session(
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
                    )
                ),
                allow_dirty_data_transfer=True,
            )
        with self.assertRaisesRegex(
            ValueError,
            "does not combine.*MESI ReadNotSharedDirty",
        ):
            self.build_resolved(
                required_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
                    )
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "dirty Unique transfer",
        ):
            self.build_resolved(
                required_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                    )
                ),
            )
        with self.assertRaisesRegex(
            ValueError,
            "shared-dirty peer handling",
        ):
            self.build_resolved(
                required_features=frozenset(
                    (
                        CHI_FEATURE_MAKE_UNIQUE,
                        CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    )
                ),
            )

    def test_submit_requires_one_512_bit_store_intent(self) -> None:
        with self.assertRaisesRegex(ValueError, "512-bit"):
            ChiSubmitMakeUnique(
                self.REQUESTER,
                self.request(),
                1 << 512,
            )


if __name__ == "__main__":
    unittest.main()
