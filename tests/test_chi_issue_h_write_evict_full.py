from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    bind_chi_issue_h_home_vdut,
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiHomeAcceptCopyBackData,
    ChiHomeAcceptWriteEvictFull,
    ChiHomeCopyBackAdmission,
    ChiHomeDirectoryEntry,
    ChiParticipantCapability,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptSnoop,
    ChiRnCopyBackOutcome,
    ChiRnIssueWriteEvictFull,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    CHI_ISSUE_H_LOGICAL_FIELD_CODEC,
    ChiChannelKind,
    ChiCleanUniqueMessage,
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCopyBackWrDataMessage,
    ChiEvictMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiReqOpcode,
    ChiRespCode,
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpRespMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
    ChiWriteBackFullMessage,
    ChiWriteEvictFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_EVICT,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_FEATURE_WRITE_EVICT_FULL,
    CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiCoherenceState,
    ChiCopyBackDeliveryPhase,
    ChiCopyBackOperation,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCleanUnique,
    ChiSubmitEvict,
    ChiSubmitWriteBackFull,
    ChiSubmitWriteEvictFull,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
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
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHWriteEvictFullTest(unittest.TestCase):
    RN = 0x07
    NEW_RN = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xE71C7
    TXN_ID = 0x15
    DBID = 0x200

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_atomic_fault(self, transition, state, rule: str) -> None:
        self.assertIsNotNone(transition.fault)
        self.assertTrue(transition.fault.rule.endswith(rule))
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

    def build_rn(
        self,
        state: ChiCacheState = ChiCacheState.UC,
    ):
        return build_chi_cache_participant_fixture(
            "clean_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    state,
                    (
                        None
                        if state in (ChiCacheState.I, ChiCacheState.UCE)
                        else self.DATA
                    ),
                ),
            ),
        )

    def build_home(
        self,
        *,
        allow_dirty_data_transfer: bool = False,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
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
                    unique_owner=self.RN,
                ),
            ),
            clean_residency_core=CacheCore(
                "home.clean",
                CacheLineStore("home.clean.lines", line_bytes=64),
            ),
            allow_dirty_data_transfer=allow_dirty_data_transfer,
            initial_data_buffer_id=self.DBID,
        )

    def build_session(
        self,
        *,
        enabled_features: frozenset = frozenset(
            (CHI_FEATURE_WRITE_EVICT_FULL,)
        ),
    ) -> ChiCoherenceSession:
        rn = self.build_rn()
        home = self.build_home(
            allow_dirty_data_transfer=(
                CHI_FEATURE_DIRTY_WRITEBACK in enabled_features
            )
        )
        return ChiCoherenceSession(
            "write_evict_session",
            home,
            {self.RN: rn},
            enabled_features=enabled_features,
            requester_node_ids=frozenset((self.RN,)),
            snoopee_node_ids=frozenset(),
        )

    def build_two_line_session(
        self,
        *,
        second_state: ChiCacheState = ChiCacheState.UC,
        enabled_features: frozenset = frozenset(
            (CHI_FEATURE_WRITE_EVICT_FULL,)
        ),
    ) -> tuple[ChiCoherenceSession, int, int]:
        second_address = self.ADDRESS + 0x40
        second_data = self.DATA ^ 0x55
        rn = build_chi_cache_participant_fixture(
            "two_line_clean_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
                ChiCacheLine(
                    second_address,
                    second_state,
                    second_data,
                ),
            ),
        )
        second_directory = (
            ChiHomeDirectoryEntry(
                second_address,
                sharers=frozenset((self.RN,)),
            )
            if second_state is ChiCacheState.SC
            else ChiHomeDirectoryEntry(
                second_address,
                unique_owner=self.RN,
            )
        )
        home = ChiCoherentHomeNode(
            "two_line_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "two_line_home.backing",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS, self.DATA),
                    BackingLine(second_address, second_data),
                ),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.RN,
                ),
                second_directory,
            ),
            clean_residency_core=CacheCore(
                "two_line_home.clean",
                CacheLineStore(
                    "two_line_home.clean.lines",
                    line_bytes=64,
                ),
            ),
            transaction_capacity=2,
            initial_data_buffer_id=self.DBID,
            allow_dirty_data_transfer=(
                CHI_FEATURE_DIRTY_WRITEBACK in enabled_features
            ),
        )
        session = ChiCoherenceSession(
            "write_evict_id_namespaces",
            home,
            {self.RN: rn},
            enabled_features=enabled_features,
            requester_node_ids=frozenset((self.RN,)),
            snoopee_node_ids=frozenset(),
        )
        return session, second_address, second_data

    @staticmethod
    def network_port(
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
    def network_link_profile(
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

    def build_resolved_network(
        self,
        *,
        with_coherence_domain: bool = True,
    ):
        builder = SystemProtocolBuilder("chi_write_evict_direct")
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx": self.network_port(
                        "tx",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx": self.network_port(
                        "rx",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "hn0",
                {
                    "rx": self.network_port(
                        "rx",
                        TransportDirection.RECEIVE,
                    ),
                    "tx": self.network_port(
                        "tx",
                        TransportDirection.TRANSMIT,
                    ),
                },
            )
        )
        forward_channels = frozenset(
            (ChiChannelKind.REQ, ChiChannelKind.DAT)
        )
        response_channels = frozenset((ChiChannelKind.RSP,))
        builder.connect_transport(
            "rn_to_hn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("rn0", "tx"),
            VirtualDutPortRef("hn0", "rx"),
            profile=self.network_link_profile(
                "rn_to_hn",
                forward_channels,
            ),
        )
        builder.connect_transport(
            "hn_to_rn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("hn0", "tx"),
            VirtualDutPortRef("rn0", "rx"),
            profile=self.network_link_profile(
                "hn_to_rn",
                response_channels,
            ),
        )
        claim_name = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                claim_name,
                VirtualDutPortRef("hn0", "rx"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts

        requester = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.RN,
            self.HOME,
            port_channels={
                "tx": forward_channels,
                "rx": response_channels,
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    ChiCacheState.UC,
                    self.DATA,
                ),
            ),
            participant_name="requester",
            binding_name="rn0",
        )
        backing_core = FullLineBackingCore(
            "hn0.backing",
            line_bytes=64,
            initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
        )
        clean_residency_core = CacheCore(
            "hn0.clean",
            CacheLineStore("hn0.clean.lines", line_bytes=64),
        )
        home = bind_chi_issue_h_home_vdut(
            duts["hn0"],
            backing_core,
            self.HOME,
            port_channels={
                "rx": forward_channels,
                "tx": response_channels,
            },
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.RN,
                ),
            ),
            clean_residency_core=clean_residency_core,
            participant_name="home",
            binding_name="hn0",
            initial_data_buffer_id=self.DBID,
        )
        return resolve_chi_system(
            system,
            facets=(
                requester.facets.facets[0],
                home.facets.facets[0],
            ),
            feature_contract=ChiFeatureContract(
                {"requester": "rn0"},
                frozenset((CHI_FEATURE_WRITE_EVICT_FULL,)),
            ),
            authority_contract=ChiCoherenceAuthorityContract(
                authorities=(
                    ChiHomeAuthority(
                        claim_name,
                        "hn0",
                        (
                            "coherent_agents"
                            if with_coherence_domain
                            else None
                        ),
                    ),
                ),
                domains=(
                    (
                        ChiCoherenceDomain(
                            "coherent_agents",
                            frozenset(("rn0",)),
                        ),
                    )
                    if with_coherence_domain
                    else ()
                ),
            ),
            feature_address_claim=claim_name,
            participant_capabilities=(
                ChiParticipantCapability(
                    "rn0",
                    CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES,
                ),
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,)
            ),
        )

    def start_copyback(self):
        rn = self.build_rn()
        home = self.build_home()
        rn_initial = rn.initial_state()
        home_initial = home.initial_state()
        request = ChiWriteEvictFullMessage(self.TXN_ID, self.ADDRESS)
        issued = self.apply(
            rn,
            rn_initial,
            ChiRnIssueWriteEvictFull(request),
        )
        accepted = self.apply(
            home,
            home_initial,
            ChiHomeAcceptWriteEvictFull(issued.emissions[0]),
        )
        copied = self.apply(
            rn,
            issued.state,
            ChiRnAcceptCompDBIDResp(accepted.emissions[0]),
        )
        return (
            rn,
            home,
            rn_initial,
            home_initial,
            request,
            issued,
            accepted,
            copied,
        )

    def test_opcode_profile_and_logical_fields_round_trip(self) -> None:
        request = ChiWriteEvictFullMessage(self.TXN_ID, self.ADDRESS)

        self.assertEqual(0x15, int(ChiReqOpcode.WRITE_EVICT_FULL))
        self.assertIs(ChiReqOpcode.WRITE_EVICT_FULL, request.opcode)
        self.assertTrue(ChiIssueHReqProfile().contains(request))

        record = CHI_ISSUE_H_LOGICAL_FIELD_CODEC.encode(request)

        self.assertEqual(
            int(ChiReqOpcode.WRITE_EVICT_FULL),
            record.fields["Opcode"],
        )
        self.assertEqual(0b1101, record.fields["MemAttr"])
        self.assertEqual(0, record.fields["CAH"])
        self.assertEqual(
            request,
            CHI_ISSUE_H_LOGICAL_FIELD_CODEC.decode(record),
        )

    def test_cah_zero_lifecycle_allocates_clean_residency(self) -> None:
        (
            rn,
            home,
            rn_initial,
            home_initial,
            request,
            issued,
            accepted,
            copied,
        ) = self.start_copyback()

        self.assertEqual(request, issued.state.pending_copybacks[
            self.TXN_ID
        ].request)
        self.assertEqual(
            ChiCacheState.UC,
            issued.state.line_at(self.ADDRESS).state,
        )
        self.assertEqual(
            self.DATA,
            issued.state.line_at(self.ADDRESS).data,
        )
        self.assertIs(
            rn_initial.cache.line_at(self.ADDRESS),
            issued.state.cache.line_at(self.ADDRESS),
        )
        self.assertEqual(self.RN, issued.emissions[0].source_id)
        self.assertEqual(self.HOME, issued.emissions[0].target_id)

        dbid_packet = accepted.emissions[0]
        self.assertIsInstance(
            dbid_packet.message,
            ChiCompDBIDRespMessage,
        )
        self.assertEqual(self.DBID, dbid_packet.message.data_buffer_id)
        self.assertIn(self.DBID, accepted.state.pending_copybacks)
        self.assertFalse(accepted.state.clean_residency.lines)
        self.assertIs(home_initial.backing, accepted.state.backing)
        self.assertEqual(
            home_initial.directory[self.ADDRESS],
            accepted.state.directory[self.ADDRESS],
        )

        rn_line = copied.state.line_at(self.ADDRESS)
        self.assertIsNotNone(rn_line)
        self.assertIs(ChiCacheState.I, rn_line.state)
        self.assertIsNone(rn_line.data)
        self.assertNotIn(self.ADDRESS, copied.state.cache.lines)
        self.assertFalse(copied.state.pending_copybacks)
        self.assertEqual(1, len(copied.emissions))
        copyback_packet = copied.emissions[0]
        self.assertIsInstance(
            copyback_packet.message,
            ChiCopyBackWrDataMessage,
        )
        copyback = copyback_packet.message
        self.assertEqual(self.DBID, copyback.transaction_id)
        self.assertEqual(self.DATA, copyback.data)
        self.assertIs(ChiRespCode.UC, copyback.response)
        self.assertEqual(0, copyback.data_id)
        self.assertEqual((1 << 64) - 1, copyback.byte_enable)
        self.assertTrue(
            ChiIssueHDatProfile(data_width=512).contains(copyback)
        )

        backing_before = accepted.state.backing.line_at(self.ADDRESS)
        committed = self.apply(
            home,
            accepted.state,
            ChiHomeAcceptCopyBackData(copyback_packet),
        )

        resident = committed.state.clean_residency.line_at(self.ADDRESS)
        self.assertIsInstance(resident, CacheLinePayload)
        self.assertEqual(self.DATA, resident.data)
        directory = committed.state.directory[self.ADDRESS]
        self.assertIsNone(directory.unique_owner)
        self.assertIsNone(directory.shared_dirty_owner)
        self.assertFalse(directory.sharers)
        self.assertIs(accepted.state.backing, committed.state.backing)
        self.assertEqual(
            backing_before,
            committed.state.backing.line_at(self.ADDRESS),
        )
        self.assertFalse(committed.state.pending_copybacks)
        self.assertFalse(committed.emissions)
        self.assertTrue(rn.is_quiescent(copied.state))
        self.assertTrue(home.is_quiescent(committed.state))

        all_messages = tuple(
            packet.message
            for transition in (issued, accepted, copied, committed)
            for packet in transition.emissions
        )
        self.assertFalse(
            any(isinstance(message, ChiCompAckMessage)
                for message in all_messages)
        )

    def test_system_tracks_req_rsp_dat_as_distinct_exact_evidence(
        self,
    ) -> None:
        session = self.build_session()
        initial = session.initial_state()
        backing_before = initial.home.backing.line_at(self.ADDRESS)
        self.assertIsNotNone(backing_before)
        request = ChiWriteEvictFullMessage(
            self.TXN_ID,
            self.ADDRESS,
        )

        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(self.RN, request),
        )
        self.assertIsInstance(
            issued.emissions[0].message,
            ChiWriteEvictFullMessage,
        )
        self.assertFalse(
            issued.state.expected_write_evict_dbid_responses
        )
        self.assertFalse(issued.state.expected_copyback_data)

        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        response_packet = accepted.emissions[0]
        response = response_packet.message
        self.assertIsInstance(response, ChiCompDBIDRespMessage)
        response_key = (self.RN, self.TXN_ID)
        self.assertEqual(
            {response_key: response_packet},
            dict(accepted.state.expected_write_evict_dbid_responses),
        )
        self.assertFalse(accepted.state.expected_copyback_data)
        response_expectation = (
            accepted.state.copyback_phase_ledger.for_request(
                self.RN,
                self.TXN_ID,
            )
        )
        self.assertIsNotNone(response_expectation)
        self.assertIs(
            ChiCopyBackOperation.WRITE_EVICT_FULL,
            response_expectation.operation,
        )
        self.assertIs(
            ChiCopyBackDeliveryPhase.HOME_RESPONSE,
            response_expectation.phase,
        )
        self.assertEqual(response_packet, response_expectation.packet)

        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(response_packet),
        )
        copyback_packet = copied.emissions[0]
        copyback = copyback_packet.message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertFalse(
            copied.state.expected_write_evict_dbid_responses
        )
        self.assertEqual(
            {(self.RN, copyback.transaction_id): copyback_packet},
            dict(copied.state.expected_copyback_data),
        )
        data_expectation = (
            copied.state.copyback_phase_ledger.for_data_buffer(
                self.RN,
                copyback.transaction_id,
            )
        )
        self.assertIsNotNone(data_expectation)
        self.assertEqual(
            response_expectation.identity,
            data_expectation.identity,
        )
        self.assertIs(
            ChiCopyBackDeliveryPhase.REQUESTER_DATA,
            data_expectation.phase,
        )
        self.assertEqual(copyback_packet, data_expectation.packet)

        committed = self.apply(
            session,
            copied.state,
            ChiDeliverCoherencePacket(copyback_packet),
        )

        self.assertTrue(session.is_quiescent(committed.state))
        self.assertFalse(
            committed.state.expected_write_evict_dbid_responses
        )
        self.assertFalse(committed.state.expected_copyback_data)
        self.assertFalse(committed.state.copyback_phase_ledger.entries)
        resident = committed.state.home.clean_residency.line_at(
            self.ADDRESS
        )
        self.assertIsNotNone(resident)
        self.assertEqual(self.DATA, resident.data)
        self.assertIs(initial.home.backing, committed.state.home.backing)
        backing_after = committed.state.home.backing.line_at(self.ADDRESS)
        self.assertEqual(backing_before, backing_after)
        self.assertEqual(backing_before.version, backing_after.version)

    def test_legacy_state_constructors_rebuild_typed_copyback_ledger(
        self,
    ) -> None:
        session = self.build_session()
        initial = session.initial_state()
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(accepted.emissions[0]),
        )

        def legacy_positional(state):
            return ChiCoherenceState(
                state.home,
                state.request_nodes,
                state.expected_evict_completions,
                state.expected_clean_unique_completions,
                state.expected_make_unique_completions,
                state.expected_coherent_read_completions,
                state.expected_writeback_dbid_responses,
                state.expected_write_evict_dbid_responses,
                state.expected_write_evict_or_evict_responses,
                state.expected_copyback_data,
                state.expected_write_evict_or_evict_acks,
                state.expected_retry_acks,
                state.expected_pcredit_grants,
                state.expected_snoop_deliveries,
                state.expected_snoop_responses,
            )

        cases = (
            (
                "home_response",
                accepted.state,
                {
                    "expected_write_evict_dbid_responses": (
                        accepted.state
                        .expected_write_evict_dbid_responses
                    )
                },
            ),
            (
                "requester_data",
                copied.state,
                {
                    "expected_copyback_data": (
                        copied.state.expected_copyback_data
                    )
                },
            ),
        )
        projection_names = (
            "expected_writeback_dbid_responses",
            "expected_write_evict_dbid_responses",
            "expected_write_evict_or_evict_responses",
            "expected_copyback_data",
            "expected_write_evict_or_evict_acks",
        )
        for phase, state, legacy_keyword in cases:
            with self.subTest(phase=phase, constructor="positional"):
                rebuilt = legacy_positional(state)
                self.assertEqual(
                    state.copyback_phase_ledger.entries,
                    rebuilt.copyback_phase_ledger.entries,
                )
                for name in projection_names:
                    self.assertEqual(
                        dict(getattr(state, name)),
                        dict(getattr(rebuilt, name)),
                    )

            with self.subTest(phase=phase, constructor="keyword"):
                rebuilt = ChiCoherenceState(
                    home=state.home,
                    request_nodes=state.request_nodes,
                    **legacy_keyword,
                )
                self.assertEqual(
                    state.copyback_phase_ledger.entries,
                    rebuilt.copyback_phase_ledger.entries,
                )
                for name in projection_names:
                    self.assertEqual(
                        dict(getattr(state, name)),
                        dict(getattr(rebuilt, name)),
                    )

    def test_system_keeps_original_txnid_and_home_dbid_namespaces(
        self,
    ) -> None:
        session, second_address, second_payload = (
            self.build_two_line_session()
        )
        initial = session.initial_state()

        first_issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(0x100, self.ADDRESS),
            ),
        )
        first_at_home = self.apply(
            session,
            first_issued.state,
            ChiDeliverCoherencePacket(first_issued.emissions[0]),
        )
        first_response = first_at_home.emissions[0].message
        self.assertIsInstance(first_response, ChiCompDBIDRespMessage)
        self.assertEqual(self.DBID, first_response.data_buffer_id)
        first_data = self.apply(
            session,
            first_at_home.state,
            ChiDeliverCoherencePacket(first_at_home.emissions[0]),
        )

        second_issued = self.apply(
            session,
            first_data.state,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(self.DBID, second_address),
            ),
        )
        second_at_home = self.apply(
            session,
            second_issued.state,
            ChiDeliverCoherencePacket(second_issued.emissions[0]),
        )
        second_response = second_at_home.emissions[0].message
        self.assertIsInstance(second_response, ChiCompDBIDRespMessage)
        self.assertEqual(self.DBID + 1, second_response.data_buffer_id)

        colliding_key = (self.RN, self.DBID)
        self.assertEqual(
            first_data.emissions[0],
            second_at_home.state.expected_copyback_data[colliding_key],
        )
        self.assertEqual(
            second_at_home.emissions[0],
            second_at_home.state
            .expected_write_evict_dbid_responses[colliding_key],
        )

        second_copied = self.apply(
            session,
            second_at_home.state,
            ChiDeliverCoherencePacket(second_at_home.emissions[0]),
        )
        first_retired = self.apply(
            session,
            second_copied.state,
            ChiDeliverCoherencePacket(first_data.emissions[0]),
        )
        retired = self.apply(
            session,
            first_retired.state,
            ChiDeliverCoherencePacket(second_copied.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        for address, data in (
            (self.ADDRESS, self.DATA),
            (second_address, second_payload),
        ):
            with self.subTest(address=address):
                backing = retired.state.home.backing.line_at(address)
                resident = retired.state.home.clean_residency.line_at(
                    address
                )
                self.assertIsNotNone(backing)
                self.assertIsNotNone(resident)
                self.assertEqual(data, backing.data)
                self.assertEqual(0, backing.version)
                self.assertEqual(data, resident.data)

    def test_original_txnid_reuse_allows_two_write_evict_data_phases(
        self,
    ) -> None:
        session, second_address, second_payload = (
            self.build_two_line_session()
        )
        original_txn_id = 0x77
        initial = session.initial_state()

        first_issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    original_txn_id,
                    self.ADDRESS,
                ),
            ),
        )
        first_at_home = self.apply(
            session,
            first_issued.state,
            ChiDeliverCoherencePacket(first_issued.emissions[0]),
        )
        first_copied = self.apply(
            session,
            first_at_home.state,
            ChiDeliverCoherencePacket(first_at_home.emissions[0]),
        )

        second_issued = self.apply(
            session,
            first_copied.state,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    original_txn_id,
                    second_address,
                ),
            ),
        )
        second_at_home = self.apply(
            session,
            second_issued.state,
            ChiDeliverCoherencePacket(second_issued.emissions[0]),
        )
        second_copied = self.apply(
            session,
            second_at_home.state,
            ChiDeliverCoherencePacket(second_at_home.emissions[0]),
        )

        first_response = first_at_home.emissions[0].message
        second_response = second_at_home.emissions[0].message
        self.assertIsInstance(first_response, ChiCompDBIDRespMessage)
        self.assertIsInstance(second_response, ChiCompDBIDRespMessage)
        self.assertEqual(original_txn_id, first_response.transaction_id)
        self.assertEqual(original_txn_id, second_response.transaction_id)
        self.assertEqual(self.DBID, first_response.data_buffer_id)
        self.assertEqual(self.DBID + 1, second_response.data_buffer_id)
        self.assertEqual(
            {
                (self.RN, self.DBID),
                (self.RN, self.DBID + 1),
            },
            set(second_copied.state.expected_copyback_data),
        )

        second_retired = self.apply(
            session,
            second_copied.state,
            ChiDeliverCoherencePacket(second_copied.emissions[0]),
        )
        retired = self.apply(
            session,
            second_retired.state,
            ChiDeliverCoherencePacket(first_copied.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        for address, payload in (
            (self.ADDRESS, self.DATA),
            (second_address, second_payload),
        ):
            with self.subTest(address=address):
                backing = retired.state.home.backing.line_at(address)
                resident = (
                    retired.state.home.clean_residency.line_at(address)
                )
                self.assertIsNotNone(backing)
                self.assertIsNotNone(resident)
                self.assertEqual(payload, backing.data)
                self.assertEqual(0, backing.version)
                self.assertEqual(payload, resident.data)

    def test_original_txnid_reuse_crosses_clean_and_dirty_copyback(
        self,
    ) -> None:
        session, second_address, second_payload = (
            self.build_two_line_session(
                second_state=ChiCacheState.UD,
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_WRITE_EVICT_FULL,
                        CHI_FEATURE_DIRTY_WRITEBACK,
                    )
                ),
            )
        )
        original_txn_id = 0x78

        first_issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    original_txn_id,
                    self.ADDRESS,
                ),
            ),
        )
        first_at_home = self.apply(
            session,
            first_issued.state,
            ChiDeliverCoherencePacket(first_issued.emissions[0]),
        )
        first_copied = self.apply(
            session,
            first_at_home.state,
            ChiDeliverCoherencePacket(first_at_home.emissions[0]),
        )

        dirty_issued = self.apply(
            session,
            first_copied.state,
            ChiSubmitWriteBackFull(
                self.RN,
                ChiWriteBackFullMessage(
                    original_txn_id,
                    second_address,
                ),
            ),
        )
        dirty_at_home = self.apply(
            session,
            dirty_issued.state,
            ChiDeliverCoherencePacket(dirty_issued.emissions[0]),
        )
        dirty_copied = self.apply(
            session,
            dirty_at_home.state,
            ChiDeliverCoherencePacket(dirty_at_home.emissions[0]),
        )

        first_response = first_at_home.emissions[0].message
        dirty_response = dirty_at_home.emissions[0].message
        self.assertIsInstance(first_response, ChiCompDBIDRespMessage)
        self.assertIsInstance(dirty_response, ChiCompDBIDRespMessage)
        self.assertEqual(original_txn_id, first_response.transaction_id)
        self.assertEqual(original_txn_id, dirty_response.transaction_id)
        self.assertEqual(self.DBID, first_response.data_buffer_id)
        self.assertEqual(self.DBID + 1, dirty_response.data_buffer_id)

        dirty_retired = self.apply(
            session,
            dirty_copied.state,
            ChiDeliverCoherencePacket(dirty_copied.emissions[0]),
        )
        retired = self.apply(
            session,
            dirty_retired.state,
            ChiDeliverCoherencePacket(first_copied.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        clean_backing = retired.state.home.backing.line_at(self.ADDRESS)
        dirty_backing = retired.state.home.backing.line_at(second_address)
        resident = retired.state.home.clean_residency.line_at(
            self.ADDRESS
        )
        self.assertIsNotNone(clean_backing)
        self.assertIsNotNone(dirty_backing)
        self.assertIsNotNone(resident)
        self.assertEqual(0, clean_backing.version)
        self.assertEqual(self.DATA, resident.data)
        self.assertEqual(second_payload, dirty_backing.data)
        self.assertEqual(1, dirty_backing.version)

    def test_original_txnid_reuse_crosses_write_evict_and_evict(
        self,
    ) -> None:
        session, second_address, _ = self.build_two_line_session(
            second_state=ChiCacheState.SC,
            enabled_features=frozenset(
                (
                    CHI_FEATURE_WRITE_EVICT_FULL,
                    CHI_FEATURE_CLEAN_EVICT,
                )
            ),
        )
        original_txn_id = 0x79

        first_issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    original_txn_id,
                    self.ADDRESS,
                ),
            ),
        )
        first_at_home = self.apply(
            session,
            first_issued.state,
            ChiDeliverCoherencePacket(first_issued.emissions[0]),
        )
        first_copied = self.apply(
            session,
            first_at_home.state,
            ChiDeliverCoherencePacket(first_at_home.emissions[0]),
        )

        evict_issued = self.apply(
            session,
            first_copied.state,
            ChiSubmitEvict(
                self.RN,
                ChiEvictMessage(original_txn_id, second_address),
            ),
        )
        evict_at_home = self.apply(
            session,
            evict_issued.state,
            ChiDeliverCoherencePacket(evict_issued.emissions[0]),
        )
        evict_retired = self.apply(
            session,
            evict_at_home.state,
            ChiDeliverCoherencePacket(evict_at_home.emissions[0]),
        )
        retired = self.apply(
            session,
            evict_retired.state,
            ChiDeliverCoherencePacket(first_copied.emissions[0]),
        )

        self.assertTrue(session.is_quiescent(retired.state))
        self.assertEqual(
            0,
            retired.state.home.backing.line_at(self.ADDRESS).version,
        )
        self.assertIsNotNone(
            retired.state.home.clean_residency.line_at(self.ADDRESS)
        )
        second_entry = retired.state.home.directory[second_address]
        self.assertFalse(second_entry.sharers)
        self.assertIsNone(second_entry.unique_owner)

    def test_system_atomically_rejects_forged_and_replayed_packets(
        self,
    ) -> None:
        session = self.build_session()
        initial = session.initial_state()
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        exact_response = accepted.emissions[0]
        response = exact_response.message
        self.assertIsInstance(response, ChiCompDBIDRespMessage)
        response_variants = {
            "DBID": replace(
                exact_response,
                message=replace(
                    response,
                    data_buffer_id=(
                        response.data_buffer_id + 1
                    ) % (1 << 12),
                ),
            ),
            "Resp": replace(
                exact_response,
                message=replace(response, response=1),
            ),
            "endpoint": replace(
                exact_response,
                source_id=self.HOME + 1,
            ),
            "packet metadata": replace(
                exact_response,
                packet_count=2,
            ),
        }
        for name, forged in response_variants.items():
            with self.subTest(packet="CompDBIDResp", field=name):
                rejected = session.step(
                    accepted.state,
                    ChiDeliverCoherencePacket(forged),
                )
                self.assert_atomic_fault(
                    rejected,
                    accepted.state,
                    "write_evict_dbid_response_correlation",
                )

        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(exact_response),
        )
        replayed_response = session.step(
            copied.state,
            ChiDeliverCoherencePacket(exact_response),
        )
        self.assert_atomic_fault(
            replayed_response,
            copied.state,
            "write_evict_dbid_response_correlation",
        )

        exact_data = copied.emissions[0]
        copyback = exact_data.message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        data_variants = {
            "data": replace(
                exact_data,
                message=replace(copyback, data=copyback.data ^ 1),
            ),
            "byte enable": replace(
                exact_data,
                message=replace(
                    copyback,
                    byte_enable=copyback.byte_enable ^ 1,
                ),
            ),
            "Resp": replace(
                exact_data,
                message=replace(
                    copyback,
                    response=ChiRespCode.SC,
                ),
            ),
            "endpoint": replace(
                exact_data,
                source_id=self.RN + 1,
            ),
            "packet metadata": replace(
                exact_data,
                packet_count=2,
            ),
        }
        for name, forged in data_variants.items():
            with self.subTest(packet="CopyBackWrData", field=name):
                rejected = session.step(
                    copied.state,
                    ChiDeliverCoherencePacket(forged),
                )
                expected_rule = (
                    "requester_authority"
                    if name == "endpoint"
                    else "copyback_correlation"
                )
                self.assert_atomic_fault(
                    rejected,
                    copied.state,
                    expected_rule,
                )

        committed = self.apply(
            session,
            copied.state,
            ChiDeliverCoherencePacket(exact_data),
        )
        replayed_data = session.step(
            committed.state,
            ChiDeliverCoherencePacket(exact_data),
        )
        self.assert_atomic_fault(
            replayed_data,
            committed.state,
            "copyback_correlation",
        )
        self.assertTrue(session.is_quiescent(committed.state))

    def test_mixed_copyback_profile_uses_generic_rule_after_retirement(
        self,
    ) -> None:
        session = self.build_session(
            enabled_features=frozenset(
                (
                    CHI_FEATURE_DIRTY_WRITEBACK,
                    CHI_FEATURE_WRITE_EVICT_FULL,
                )
            )
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        exact_response = accepted.emissions[0]
        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(exact_response),
        )

        replayed = session.step(
            copied.state,
            ChiDeliverCoherencePacket(exact_response),
        )

        self.assert_atomic_fault(
            replayed,
            copied.state,
            "copyback_dbid_response_correlation",
        )

    def test_resolved_network_runs_exact_req_rsp_dat_witness(
        self,
    ) -> None:
        resolved = self.build_resolved_network()

        self.assertTrue(resolved.is_closed)
        evidence = resolved.capabilities.require(
            CHI_FEATURE_WRITE_EVICT_FULL
        )
        self.assertEqual(
            {
                "write_evict_request",
                "write_evict_dbid_response",
                "write_evict_copyback_data",
            },
            set(evidence.flows),
        )
        self.assertEqual(
            ("rn_to_hn",),
            evidence.flows["write_evict_request"].connections,
        )
        self.assertEqual(
            ("hn_to_rn",),
            evidence.flows["write_evict_dbid_response"].connections,
        )
        self.assertEqual(
            ("rn_to_hn",),
            evidence.flows["write_evict_copyback_data"].connections,
        )

        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        initial = session.initial_state()
        initial_backing = initial.coherence.home.backing.line_at(
            self.ADDRESS
        )
        self.assertIsNotNone(initial_backing)
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )

        run = session.run_until_quiescent(
            issued.state,
            max_steps=256,
        )

        self.assertIs(Verdict.PASS, run.verdict)
        self.assertIsNone(run.blocked)
        self.assertTrue(session.is_quiescent(run.final_state))
        endpoint_events = tuple(
            event
            for event in run.emissions
            if event.kind
            is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
        )
        self.assertEqual(3, len(endpoint_events))
        packets = tuple(event.packet for event in endpoint_events)
        self.assertTrue(all(packet is not None for packet in packets))
        request_packet, response_packet, data_packet = packets
        assert request_packet is not None
        assert response_packet is not None
        assert data_packet is not None
        self.assertEqual(
            (
                ChiWriteEvictFullMessage,
                ChiCompDBIDRespMessage,
                ChiCopyBackWrDataMessage,
            ),
            tuple(type(packet.message) for packet in packets),
        )
        self.assertEqual(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            ),
            tuple(packet.channel for packet in packets),
        )
        self.assertNotIn(
            ChiChannelKind.SNP,
            tuple(packet.channel for packet in packets),
        )
        self.assertFalse(
            any(
                isinstance(packet.message, ChiCompAckMessage)
                for packet in packets
            )
        )

        request_event, response_event, data_event = endpoint_events
        self.assertEqual(
            request_event.lineage,
            response_event.lineage[: len(request_event.lineage)],
        )
        self.assertEqual(
            response_event.lineage,
            data_event.lineage[: len(response_event.lineage)],
        )
        route_segments = (
            (
                request_event.lineage,
                "rn_to_hn@",
            ),
            (
                response_event.lineage[len(request_event.lineage) :],
                "hn_to_rn@",
            ),
            (
                data_event.lineage[len(response_event.lineage) :],
                "rn_to_hn@",
            ),
        )
        for lineage, prefix in route_segments:
            with self.subTest(route_prefix=prefix):
                self.assertTrue(
                    any(item.startswith(prefix) for item in lineage),
                    (prefix, lineage),
                )

        response = response_packet.message
        copyback = data_packet.message
        self.assertIsInstance(response, ChiCompDBIDRespMessage)
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertEqual(self.TXN_ID, response.transaction_id)
        self.assertEqual(
            response.data_buffer_id,
            copyback.transaction_id,
        )
        self.assertIs(ChiRespCode.UC, copyback.response)
        self.assertEqual(self.DATA, copyback.data)
        self.assertEqual((1 << 64) - 1, copyback.byte_enable)
        self.assertEqual(0, copyback.data_id)

        final = run.final_state.coherence
        rn_state = final.request_nodes[self.RN]
        home_state = final.home
        self.assertIs(
            ChiCacheState.I,
            rn_state.permissions[self.ADDRESS],
        )
        self.assertNotIn(self.ADDRESS, rn_state.cache.lines)
        self.assertFalse(rn_state.pending_copybacks)
        resident = home_state.clean_residency.line_at(self.ADDRESS)
        self.assertIsNotNone(resident)
        self.assertEqual(self.DATA, resident.data)
        directory = home_state.directory[self.ADDRESS]
        self.assertIsNone(directory.unique_owner)
        self.assertIsNone(directory.shared_dirty_owner)
        self.assertFalse(directory.sharers)
        final_backing = home_state.backing.line_at(self.ADDRESS)
        self.assertEqual(initial_backing, final_backing)
        self.assertEqual(initial_backing.version, final_backing.version)
        self.assertFalse(home_state.pending_copybacks)
        self.assertFalse(final.expected_write_evict_dbid_responses)
        self.assertFalse(final.expected_copyback_data)

    def test_resolved_feature_requires_home_coherence_domain(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "does not select a coherence domain",
        ):
            self.build_resolved_network(with_coherence_domain=False)

    def test_rejects_non_uc_initial_permissions_without_mutation(self) -> None:
        for initial_state in (
            ChiCacheState.I,
            ChiCacheState.SC,
            ChiCacheState.UCE,
            ChiCacheState.UD,
            ChiCacheState.SD,
        ):
            with self.subTest(initial_state=initial_state):
                rn = self.build_rn(initial_state)
                state = rn.initial_state()
                transition = rn.step(
                    state,
                    ChiRnIssueWriteEvictFull(
                        ChiWriteEvictFullMessage(
                            self.TXN_ID,
                            self.ADDRESS,
                        )
                    ),
                )

                self.assert_atomic_fault(
                    transition,
                    state,
                    "write_evict_permission",
                )

    def test_rejects_invalid_request_attributes_without_mutation(self) -> None:
        valid = ChiWriteEvictFullMessage(self.TXN_ID, self.ADDRESS)
        cases = (
            ("size", replace(valid, size=5), "write_evict_shape"),
            (
                "MemAttr",
                replace(valid, memory_attributes=0b0101),
                "write_evict_request_attributes",
            ),
            (
                "SnpAttr",
                replace(valid, snoop_attribute=False),
                "write_evict_request_attributes",
            ),
            (
                "ExpCompAck",
                replace(valid, expect_completion_ack=True),
                "write_evict_request_attributes",
            ),
        )

        for field_name, request, rule in cases:
            with self.subTest(field=field_name):
                self.assertTrue(ChiIssueHReqProfile().explain(request))
                rn = self.build_rn()
                state = rn.initial_state()
                transition = rn.step(
                    state,
                    ChiRnIssueWriteEvictFull(request),
                )

                self.assert_atomic_fault(transition, state, rule)

    def test_home_rejects_partial_byte_enable_without_commit(self) -> None:
        (
            _,
            home,
            _,
            _,
            _,
            _,
            accepted,
            copied,
        ) = self.start_copyback()
        copyback_packet = copied.emissions[0]
        malformed = replace(
            copyback_packet,
            message=replace(
                copyback_packet.message,
                byte_enable=(1 << 64) - 2,
            ),
        )

        rejected = home.step(
            accepted.state,
            ChiHomeAcceptCopyBackData(malformed),
        )

        self.assert_atomic_fault(
            rejected,
            accepted.state,
            "write_evict_copyback_profile",
        )
        self.assertFalse(accepted.state.clean_residency.lines)
        self.assertEqual(
            self.RN,
            accepted.state.directory[self.ADDRESS].unique_owner,
        )

    def test_second_same_line_issue_is_blocked(self) -> None:
        rn = self.build_rn()
        initial = rn.initial_state()
        issued = self.apply(
            rn,
            initial,
            ChiRnIssueWriteEvictFull(
                ChiWriteEvictFullMessage(self.TXN_ID, self.ADDRESS)
            ),
        )

        blocked = rn.step(
            issued.state,
            ChiRnIssueWriteEvictFull(
                ChiWriteEvictFullMessage(self.TXN_ID + 1, self.ADDRESS)
            ),
        )

        self.assertIsNone(blocked.fault)
        self.assertIsNotNone(blocked.blocked)
        self.assertIs(issued.state, blocked.state)
        self.assertFalse(blocked.emissions)

    def test_pre_dbid_invalidating_snoop_cancels_payload_but_keeps_correlation(
        self,
    ) -> None:
        snoops = (
            ChiSnpUniqueMessage(0x100, self.ADDRESS),
            ChiSnpCleanInvalidMessage(0x101, self.ADDRESS),
            ChiSnpMakeInvalidMessage(0x102, self.ADDRESS),
        )
        for snoop_message in snoops:
            with self.subTest(snoop=type(snoop_message).__name__):
                rn = self.build_rn()
                issued = self.apply(
                    rn,
                    rn.initial_state(),
                    ChiRnIssueWriteEvictFull(
                        ChiWriteEvictFullMessage(
                            self.TXN_ID,
                            self.ADDRESS,
                        )
                    ),
                )
                snooped = self.apply(
                    rn,
                    issued.state,
                    ChiRnAcceptSnoop(
                        ChiNetworkPacket.snoop(
                            snoop_message,
                            source_id=self.HOME,
                            target_id=self.RN,
                        )
                    ),
                )

                line = snooped.state.line_at(self.ADDRESS)
                self.assertIsNotNone(line)
                self.assertIs(ChiCacheState.I, line.state)
                self.assertIsNone(line.data)
                self.assertNotIn(self.ADDRESS, snooped.state.cache.lines)
                self.assertEqual(
                    issued.state.pending_copybacks[self.TXN_ID].request,
                    snooped.state.pending_copybacks[self.TXN_ID].request,
                )
                self.assertIs(
                    ChiRnCopyBackOutcome.CANCELED_I,
                    snooped.state.pending_copybacks[
                        self.TXN_ID
                    ].outcome,
                )
                self.assertEqual(1, len(snooped.emissions))
                snoop_response = snooped.emissions[0]
                self.assertIsInstance(
                    snoop_response.message,
                    ChiSnpRespMessage,
                )
                self.assertIs(
                    ChiRespCode.I,
                    snoop_response.message.response,
                )
                self.assertEqual(
                    snoop_message.transaction_id,
                    snoop_response.message.transaction_id,
                )

                dbid = ChiNetworkPacket.response(
                    ChiCompDBIDRespMessage(
                        transaction_id=self.TXN_ID,
                        data_buffer_id=self.DBID,
                    ),
                    source_id=self.HOME,
                    target_id=self.RN,
                )
                canceled = self.apply(
                    rn,
                    snooped.state,
                    ChiRnAcceptCompDBIDResp(dbid),
                )

                self.assertFalse(canceled.state.pending_copybacks)
                self.assertEqual(1, len(canceled.emissions))
                copyback = canceled.emissions[0].message
                self.assertIsInstance(
                    copyback,
                    ChiCopyBackWrDataMessage,
                )
                self.assertEqual(self.DBID, copyback.transaction_id)
                self.assertIs(ChiRespCode.I, copyback.response)
                self.assertEqual(0, copyback.data)
                self.assertEqual(0, copyback.byte_enable)

    def test_pre_dbid_snp_shared_retires_cah_zero_with_sc_data(
        self,
    ) -> None:
        rn = self.build_rn()
        issued = self.apply(
            rn,
            rn.initial_state(),
            ChiRnIssueWriteEvictFull(
                ChiWriteEvictFullMessage(self.TXN_ID, self.ADDRESS)
            ),
        )
        snooped = self.apply(
            rn,
            issued.state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpSharedMessage(0x100, self.ADDRESS),
                    source_id=self.HOME,
                    target_id=self.RN,
                )
            ),
        )

        line = snooped.state.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.SC, line.state)
        self.assertEqual(self.DATA, line.data)
        pending = snooped.state.pending_copybacks[self.TXN_ID]
        self.assertFalse(pending.request.copy_at_home)
        self.assertIs(ChiRnCopyBackOutcome.LIVE_SC, pending.outcome)
        snoop_response = snooped.emissions[0].message
        self.assertIsInstance(snoop_response, ChiSnpRespMessage)
        self.assertIs(ChiRespCode.SC, snoop_response.response)

        copied = self.apply(
            rn,
            snooped.state,
            ChiRnAcceptCompDBIDResp(
                ChiNetworkPacket.response(
                    ChiCompDBIDRespMessage(
                        transaction_id=self.TXN_ID,
                        data_buffer_id=self.DBID,
                    ),
                    source_id=self.HOME,
                    target_id=self.RN,
                )
            ),
        )

        self.assertFalse(copied.state.pending_copybacks)
        retired = copied.state.line_at(self.ADDRESS)
        self.assertIsNotNone(retired)
        assert retired is not None
        self.assertIs(ChiCacheState.I, retired.state)
        self.assertIsNone(retired.data)
        self.assertEqual(1, len(copied.emissions))
        copyback = copied.emissions[0].message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertEqual(self.DBID, copyback.transaction_id)
        self.assertIs(ChiRespCode.SC, copyback.response)
        self.assertEqual(self.DATA, copyback.data)
        self.assertEqual((1 << 64) - 1, copyback.byte_enable)
        self.assertTrue(rn.is_quiescent(copied.state))

    def test_clean_unique_snoop_cancels_delayed_write_evict_exactly(
        self,
    ) -> None:
        old_owner = self.build_rn()
        new_owner = build_chi_cache_participant_fixture(
            "new_clean_owner",
            self.NEW_RN,
            self.HOME,
        )
        session = ChiCoherenceSession(
            "clean_unique_write_evict_cancel",
            self.build_home(),
            {
                self.RN: old_owner,
                self.NEW_RN: new_owner,
            },
            enabled_features=frozenset(
                (
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    CHI_FEATURE_WRITE_EVICT_FULL,
                )
            ),
            requester_node_ids=frozenset((self.RN, self.NEW_RN)),
            snoopee_node_ids=frozenset((self.RN, self.NEW_RN)),
        )
        initial = session.initial_state()
        backing_before = initial.home.backing.line_at(self.ADDRESS)

        write_evict_issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                ),
            ),
        )
        delayed_write_evict = write_evict_issued.emissions[0]
        clean_unique_issued = self.apply(
            session,
            write_evict_issued.state,
            ChiSubmitCleanUnique(
                self.NEW_RN,
                ChiCleanUniqueMessage(
                    self.TXN_ID + 1,
                    self.ADDRESS,
                ),
            ),
        )
        clean_unique_at_home = self.apply(
            session,
            clean_unique_issued.state,
            ChiDeliverCoherencePacket(
                clean_unique_issued.emissions[0]
            ),
        )
        snoop_packet = clean_unique_at_home.emissions[0]
        self.assertIsInstance(
            snoop_packet.message,
            ChiSnpCleanInvalidMessage,
        )
        snoop_key = (
            self.RN,
            snoop_packet.message.transaction_id,
        )
        self.assertEqual(
            snoop_packet,
            clean_unique_at_home.state.expected_snoop_deliveries[
                snoop_key
            ],
        )

        old_owner_snooped = self.apply(
            session,
            clean_unique_at_home.state,
            ChiDeliverCoherencePacket(snoop_packet),
        )
        old_state = old_owner_snooped.state.request_nodes[self.RN]
        old_line = old_state.line_at(self.ADDRESS)
        self.assertIsNotNone(old_line)
        self.assertIs(ChiCacheState.I, old_line.state)
        self.assertIsNone(old_line.data)
        self.assertIn(self.TXN_ID, old_state.pending_copybacks)
        snoop_response = old_owner_snooped.emissions[0]
        self.assertIsInstance(
            snoop_response.message,
            ChiSnpRespMessage,
        )
        self.assertIs(ChiRespCode.I, snoop_response.message.response)
        self.assertNotIn(
            snoop_key,
            old_owner_snooped.state.expected_snoop_deliveries,
        )
        self.assertEqual(
            snoop_response,
            old_owner_snooped.state.expected_snoop_responses[snoop_key],
        )

        clean_unique_collected = self.apply(
            session,
            old_owner_snooped.state,
            ChiDeliverCoherencePacket(snoop_response),
        )
        new_owner_completed = self.apply(
            session,
            clean_unique_collected.state,
            ChiDeliverCoherencePacket(
                clean_unique_collected.emissions[0]
            ),
        )
        clean_unique_retired = self.apply(
            session,
            new_owner_completed.state,
            ChiDeliverCoherencePacket(
                new_owner_completed.emissions[0]
            ),
        )
        directory_after_snoop = clean_unique_retired.state.home.directory[
            self.ADDRESS
        ]
        backing_after_snoop = (
            clean_unique_retired.state.home.backing.line_at(self.ADDRESS)
        )
        clean_after_snoop = clean_unique_retired.state.home.clean_residency
        self.assertEqual(self.NEW_RN, directory_after_snoop.unique_owner)
        self.assertEqual(backing_before, backing_after_snoop)
        self.assertFalse(clean_after_snoop.lines)

        canceled_at_home = self.apply(
            session,
            clean_unique_retired.state,
            ChiDeliverCoherencePacket(delayed_write_evict),
        )
        exact_response = canceled_at_home.emissions[0]
        home_pending = next(
            iter(canceled_at_home.state.home.pending_copybacks.values())
        )
        self.assertIs(
            ChiHomeCopyBackAdmission.SNOOP_CANCELED,
            home_pending.admission,
        )
        self.assertEqual(
            exact_response,
            canceled_at_home.state.expected_write_evict_dbid_responses[
                (self.RN, self.TXN_ID)
            ],
        )
        cancel_sent = self.apply(
            session,
            canceled_at_home.state,
            ChiDeliverCoherencePacket(exact_response),
        )
        exact_copyback = cancel_sent.emissions[0]
        copyback = exact_copyback.message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        self.assertIs(ChiRespCode.I, copyback.response)
        self.assertEqual(0, copyback.data)
        self.assertEqual(0, copyback.byte_enable)
        self.assertEqual(
            exact_copyback,
            cancel_sent.state.expected_copyback_data[
                (self.RN, copyback.transaction_id)
            ],
        )

        forged_payload = replace(
            exact_copyback,
            message=replace(
                copyback,
                data=self.DATA,
                response=ChiRespCode.UC,
                byte_enable=(1 << 64) - 1,
            ),
        )
        rejected = session.step(
            cancel_sent.state,
            ChiDeliverCoherencePacket(forged_payload),
        )
        self.assert_atomic_fault(
            rejected,
            cancel_sent.state,
            "copyback_correlation",
        )

        retired = self.apply(
            session,
            cancel_sent.state,
            ChiDeliverCoherencePacket(exact_copyback),
        )
        self.assertEqual(
            directory_after_snoop,
            retired.state.home.directory[self.ADDRESS],
        )
        self.assertEqual(
            backing_after_snoop,
            retired.state.home.backing.line_at(self.ADDRESS),
        )
        self.assertEqual(
            clean_after_snoop,
            retired.state.home.clean_residency,
        )
        self.assertFalse(retired.state.home.pending_copybacks)
        self.assertFalse(retired.state.expected_copyback_data)
        self.assertTrue(session.is_quiescent(retired.state))

        replayed_request = session.step(
            retired.state,
            ChiDeliverCoherencePacket(delayed_write_evict),
        )
        self.assert_atomic_fault(
            replayed_request,
            retired.state,
            "write_evict_admission_evidence",
        )


if __name__ == "__main__":
    unittest.main()
