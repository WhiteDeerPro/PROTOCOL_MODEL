from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    bind_chi_issue_h_home_vdut,
    build_chi_cache_participant_fixture,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCopyBackDecision,
    ChiHomeCopyBackAdmission,
    ChiHomeDirectoryEntry,
    ChiParticipantCapability,
    ChiRnCopyBackOutcome,
    ChiRnIssueWriteEvictFull,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCleanUniqueMessage,
    ChiCompAckMessage,
    ChiCompDataMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiReadUniqueMessage,
    ChiRespCode,
    ChiSnpCleanInvalidMessage,
    ChiSnpRespMessage,
    ChiWriteEvictFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_WRITE_EVICT_FULL,
    CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE,
    CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiCopyBackDeliveryPhase,
    ChiCopyBackOperation,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCleanUnique,
    ChiSubmitCoherentRead,
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


class ChiIssueHWriteEvictFullCopyAtHomeSystemTest(
    unittest.TestCase
):
    RN = 0x07
    NEW_RN = 0x08
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xCA11_600D
    READ_TXN_ID = 0x119
    WRITE_EVICT_TXN_ID = 0x11A
    DBID = 0x220

    FEATURES = frozenset(
        (
            CHI_FEATURE_CLEAN_READ_UNIQUE,
            CHI_FEATURE_WRITE_EVICT_FULL,
            CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,
        )
    )

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_atomic_fault(
        self,
        transition,
        state,
        suffix: str | None = None,
    ) -> None:
        self.assertIsNotNone(transition.fault)
        if suffix is not None:
            self.assertTrue(
                transition.fault.rule.endswith(suffix),
                transition.fault.rule,
            )
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

    def build_rn(
        self,
        *,
        resident: bool = True,
        copy_at_home: bool = True,
    ):
        return build_chi_cache_participant_fixture(
            "copy_at_home_system_cache",
            self.RN,
            self.HOME,
            initial_lines=(
                (
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.UC,
                        self.DATA,
                        copy_at_home=copy_at_home,
                    ),
                )
                if resident
                else ()
            ),
        )

    def build_home(
        self,
        decision: ChiCopyBackDecision,
        *,
        initial_owner: bool = True,
        current_copy: bool = True,
        read_policy: bool = True,
        write_policy: bool = True,
    ) -> ChiCoherentHomeNode:
        return ChiCoherentHomeNode(
            "copy_at_home_system_home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "copy_at_home_system_home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=(self.RN if initial_owner else None),
                ),
            ),
            clean_residency_core=CacheCore(
                "copy_at_home_system_home.clean",
                CacheLineStore(
                    "copy_at_home_system_home.clean.lines",
                    line_bytes=64,
                    initial_lines=(
                        (
                            CacheLinePayload(
                                self.ADDRESS,
                                self.DATA,
                            ),
                        )
                        if current_copy
                        else ()
                    ),
                ),
            ),
            initial_data_buffer_id=self.DBID,
            read_unique_copy_at_home_policy=(
                (
                    lambda request, state: (
                        state.clean_residency.line_at(request.address)
                        is not None
                    )
                )
                if read_policy
                else None
            ),
            write_evict_full_current_copy_policy=(
                (lambda _request, _state: decision)
                if write_policy
                else None
            ),
        )

    def build_session(
        self,
        decision: ChiCopyBackDecision,
        *,
        resident: bool = True,
        initial_owner: bool = True,
        current_copy: bool = True,
    ) -> ChiCoherenceSession:
        return ChiCoherenceSession(
            "copy_at_home_system_session",
            self.build_home(
                decision,
                initial_owner=initial_owner,
                current_copy=current_copy,
            ),
            {
                self.RN: self.build_rn(
                    resident=resident,
                    copy_at_home=resident,
                )
            },
            enabled_features=self.FEATURES,
            requester_node_ids=frozenset((self.RN,)),
            snoopee_node_ids=frozenset(),
        )

    def build_multi_requester_session(
        self,
        decision: ChiCopyBackDecision,
        *,
        name: str,
        current_copy: bool = True,
    ) -> ChiCoherenceSession:
        return ChiCoherenceSession(
            name,
            self.build_home(decision, current_copy=current_copy),
            {
                self.RN: self.build_rn(),
                self.NEW_RN: build_chi_cache_participant_fixture(
                    f"{name}.new_owner",
                    self.NEW_RN,
                    self.HOME,
                ),
            },
            enabled_features=(
                self.FEATURES
                | frozenset((CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,))
            ),
            requester_node_ids=frozenset((self.RN, self.NEW_RN)),
            snoopee_node_ids=frozenset((self.RN, self.NEW_RN)),
        )

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
        decision: ChiCopyBackDecision,
    ):
        builder = SystemProtocolBuilder(
            f"chi_copy_at_home_{decision.value}"
        )
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
        requester_to_home = frozenset(
            (
                ChiChannelKind.REQ,
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            )
        )
        home_to_requester = frozenset(
            (
                ChiChannelKind.RSP,
                ChiChannelKind.DAT,
            )
        )
        builder.connect_transport(
            "rn_to_hn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("rn0", "tx"),
            VirtualDutPortRef("hn0", "rx"),
            profile=self.network_link_profile(
                "rn_to_hn",
                requester_to_home,
            ),
        )
        builder.connect_transport(
            "hn_to_rn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("hn0", "tx"),
            VirtualDutPortRef("rn0", "rx"),
            profile=self.network_link_profile(
                "hn_to_rn",
                home_to_requester,
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
                "tx": requester_to_home,
                "rx": home_to_requester,
            },
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
            CacheLineStore(
                "hn0.clean.lines",
                line_bytes=64,
                initial_lines=(
                    CacheLinePayload(self.ADDRESS, self.DATA),
                ),
            ),
        )
        home = bind_chi_issue_h_home_vdut(
            duts["hn0"],
            backing_core,
            self.HOME,
            port_channels={
                "rx": requester_to_home,
                "tx": home_to_requester,
            },
            initial_directory=(
                ChiHomeDirectoryEntry(self.ADDRESS),
            ),
            clean_residency_core=clean_residency_core,
            participant_name="home",
            binding_name="hn0",
            initial_data_buffer_id=self.DBID,
            read_unique_copy_at_home_policy=(
                lambda request, state: (
                    state.clean_residency.line_at(request.address)
                    is not None
                )
            ),
            write_evict_full_current_copy_policy=(
                lambda _request, _state: decision
            ),
        )
        return resolve_chi_system(
            system,
            facets=(
                requester.facets.facets[0],
                home.facets.facets[0],
            ),
            feature_contract=ChiFeatureContract(
                {"requester": "rn0"},
                frozenset(
                    (CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,)
                ),
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
                        frozenset(("rn0",)),
                    ),
                ),
            ),
            feature_address_claim=claim_name,
            participant_capabilities=(
                ChiParticipantCapability(
                    "rn0",
                    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                    | CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES
                    | (
                        CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES
                    ),
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                    | CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES
                    | (
                        CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES
                    ),
                ),
            ),
            system_capabilities=frozenset(
                (
                    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                    CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,
                    (
                        CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE
                    ),
                )
            ),
        )

    def start_write_evict(
        self,
        decision: ChiCopyBackDecision,
    ):
        session = self.build_session(decision)
        initial = session.initial_state()
        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(self.RN, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        return session, initial, request, issued, accepted

    def assert_final_clean_victim(
        self,
        session: ChiCoherenceSession,
        initial,
        final,
    ) -> None:
        self.assertTrue(session.is_quiescent(final))
        self.assertFalse(final.copyback_phase_ledger.entries)

        rn_state = final.request_nodes[self.RN]
        line = rn_state.line_at(self.ADDRESS)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.I, line.state)
        self.assertIsNone(line.data)
        self.assertFalse(line.copy_at_home)
        self.assertNotIn(self.ADDRESS, rn_state.cache.lines)
        self.assertNotIn(self.ADDRESS, rn_state.copy_at_home_lines)
        self.assertFalse(rn_state.pending_copybacks)

        home_state = final.home
        entry = home_state.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertIsNone(entry.shared_dirty_owner)
        self.assertFalse(entry.sharers)
        self.assertFalse(home_state.pending_copybacks)
        resident = home_state.clean_residency.line_at(self.ADDRESS)
        self.assertIsNotNone(resident)
        assert resident is not None
        self.assertEqual(self.DATA, resident.data)

        before = initial.home.backing.line_at(self.ADDRESS)
        after = home_state.backing.line_at(self.ADDRESS)
        self.assertIsNotNone(before)
        self.assertEqual(before, after)
        self.assertEqual(0, after.version)
        self.assertIs(initial.home.backing, home_state.backing)

    def test_constructor_requires_modifier_dependencies_and_both_policies(
        self,
    ) -> None:
        rn = self.build_rn()
        no_policies = self.build_home(
            ChiCopyBackDecision.REQUEST_DATA,
            read_policy=False,
            write_policy=False,
        )
        with self.assertRaisesRegex(
            ValueError,
            "requires explicit ReadUnique producer and WriteEvictFull "
            "outcome policies",
        ):
            ChiCoherenceSession(
                "missing_copy_at_home_policies",
                no_policies,
                {self.RN: rn},
                enabled_features=self.FEATURES,
            )

        for read_policy, write_policy in ((True, False), (False, True)):
            with self.subTest(
                read_policy=read_policy,
                write_policy=write_policy,
            ):
                partial = self.build_home(
                    ChiCopyBackDecision.REQUEST_DATA,
                    read_policy=read_policy,
                    write_policy=write_policy,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "requires explicit ReadUnique producer and "
                    "WriteEvictFull outcome policies",
                ):
                    ChiCoherenceSession(
                        "partial_copy_at_home_policies",
                        partial,
                        {self.RN: rn},
                        enabled_features=self.FEATURES,
                    )

        configured = self.build_home(
            ChiCopyBackDecision.REQUEST_DATA
        )
        with self.assertRaisesRegex(
            ValueError,
            "configured Home CopyAtHome policies require",
        ):
            ChiCoherenceSession(
                "policies_without_modifier",
                configured,
                {self.RN: rn},
                enabled_features=frozenset(
                    (
                        CHI_FEATURE_CLEAN_READ_UNIQUE,
                        CHI_FEATURE_WRITE_EVICT_FULL,
                    )
                ),
            )

        with self.assertRaisesRegex(
            ValueError,
            "requires the clean ReadUnique and WriteEvictFull base",
        ):
            ChiCoherenceSession(
                "modifier_without_dependencies",
                configured,
                {self.RN: rn},
                enabled_features=frozenset(
                    (CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,)
                ),
            )

    def test_submit_and_delivery_require_the_copy_at_home_modifier(
        self,
    ) -> None:
        rn = self.build_rn()
        home = self.build_home(
            ChiCopyBackDecision.REQUEST_DATA,
            read_policy=False,
            write_policy=False,
        )
        session = ChiCoherenceSession(
            "copy_at_home_feature_gate",
            home,
            {self.RN: rn},
            enabled_features=frozenset(
                (CHI_FEATURE_WRITE_EVICT_FULL,)
            ),
            requester_node_ids=frozenset((self.RN,)),
            snoopee_node_ids=frozenset(),
        )
        initial = session.initial_state()
        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )

        rejected_submit = session.step(
            initial,
            ChiSubmitWriteEvictFull(self.RN, request),
        )
        self.assert_atomic_fault(
            rejected_submit,
            initial,
            "write_evict_copy_at_home_feature",
        )

        rn_issued = self.apply(
            rn,
            initial.request_nodes[self.RN],
            ChiRnIssueWriteEvictFull(request),
        )
        delivery_state = replace(
            initial,
            request_nodes={self.RN: rn_issued.state},
        )
        rejected_delivery = session.step(
            delivery_state,
            ChiDeliverCoherencePacket(rn_issued.emissions[0]),
        )
        self.assert_atomic_fault(
            rejected_delivery,
            delivery_state,
            "write_evict_copy_at_home_feature",
        )

    def test_data_path_uses_exact_typed_phases_and_rejects_swaps(
        self,
    ) -> None:
        (
            session,
            initial,
            request,
            issued,
            accepted,
        ) = self.start_write_evict(ChiCopyBackDecision.REQUEST_DATA)
        response_packet = accepted.emissions[0]
        response = response_packet.message
        self.assertIsInstance(response, ChiCompDBIDRespMessage)

        expectation = accepted.state.copyback_phase_ledger.for_request(
            self.RN,
            request.transaction_id,
        )
        self.assertIsNotNone(expectation)
        assert expectation is not None
        self.assertIs(
            ChiCopyBackOperation.WRITE_EVICT_FULL,
            expectation.operation,
        )
        self.assertIs(
            ChiCopyBackDeliveryPhase.HOME_RESPONSE,
            expectation.phase,
        )
        self.assertEqual(response_packet, expectation.packet)
        self.assertEqual(
            (self.RN, request.transaction_id, response.data_buffer_id),
            (
                expectation.identity.requester_id,
                expectation.identity.request_transaction_id,
                expectation.identity.data_buffer_id,
            ),
        )

        wrong_dbid_response = replace(
            response_packet,
            message=replace(
                response,
                data_buffer_id=response.data_buffer_id + 1,
            ),
        )
        rejected_dbid = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(wrong_dbid_response),
        )
        self.assert_atomic_fault(
            rejected_dbid,
            accepted.state,
            "write_evict_dbid_response_correlation",
        )

        terminal_swap = replace(
            response_packet,
            message=ChiCompMessage(
                request.transaction_id,
                response.data_buffer_id,
                response=ChiRespCode.I,
            ),
        )
        rejected_swap = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(terminal_swap),
        )
        self.assert_atomic_fault(
            rejected_swap,
            accepted.state,
            "write_evict_copy_at_home_completion_correlation",
        )

        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(response_packet),
        )
        copyback_packet = copied.emissions[0]
        copyback = copyback_packet.message
        self.assertIsInstance(copyback, ChiCopyBackWrDataMessage)
        data_expectation = (
            copied.state.copyback_phase_ledger.for_data_buffer(
                self.RN,
                copyback.transaction_id,
            )
        )
        self.assertIsNotNone(data_expectation)
        assert data_expectation is not None
        self.assertEqual(expectation.identity, data_expectation.identity)
        self.assertIs(
            ChiCopyBackDeliveryPhase.REQUESTER_DATA,
            data_expectation.phase,
        )
        self.assertEqual(copyback_packet, data_expectation.packet)

        forged_dbid_data = replace(
            copyback_packet,
            message=replace(
                copyback,
                transaction_id=copyback.transaction_id + 1,
            ),
        )
        rejected_data = session.step(
            copied.state,
            ChiDeliverCoherencePacket(forged_dbid_data),
        )
        self.assert_atomic_fault(
            rejected_data,
            copied.state,
            "copyback_correlation",
        )

        swapped_ack = ChiNetworkPacket.response(
            ChiCompAckMessage(
                copyback.transaction_id,
                response=ChiRespCode.UC,
            ),
            source_id=self.RN,
            target_id=self.HOME,
        )
        rejected_ack = session.step(
            copied.state,
            ChiDeliverCoherencePacket(swapped_ack),
        )
        self.assert_atomic_fault(
            rejected_ack,
            copied.state,
            "write_evict_copy_at_home_ack_correlation",
        )

        committed = self.apply(
            session,
            copied.state,
            ChiDeliverCoherencePacket(copyback_packet),
        )
        self.assert_final_clean_victim(
            session,
            initial,
            committed.state,
        )

        replay = session.step(
            committed.state,
            ChiDeliverCoherencePacket(copyback_packet),
        )
        self.assert_atomic_fault(
            replay,
            committed.state,
            "copyback_correlation",
        )

        self.assertEqual(
            request,
            issued.state.request_nodes[self.RN]
            .pending_copybacks[request.transaction_id]
            .request,
        )

    def test_no_data_path_uses_ack_phase_and_rejects_swaps(
        self,
    ) -> None:
        (
            session,
            initial,
            request,
            _issued,
            accepted,
        ) = self.start_write_evict(
            ChiCopyBackDecision.COMPLETE_WITHOUT_DATA
        )
        response_packet = accepted.emissions[0]
        response = response_packet.message
        self.assertIsInstance(response, ChiCompMessage)
        self.assertIs(ChiRespCode.I, response.response)

        expectation = accepted.state.copyback_phase_ledger.for_request(
            self.RN,
            request.transaction_id,
        )
        self.assertIsNotNone(expectation)
        assert expectation is not None
        self.assertIs(
            ChiCopyBackOperation.WRITE_EVICT_FULL,
            expectation.operation,
        )
        self.assertIs(
            ChiCopyBackDeliveryPhase.HOME_RESPONSE,
            expectation.phase,
        )
        self.assertEqual(response_packet, expectation.packet)

        wrong_dbid_response = replace(
            response_packet,
            message=replace(
                response,
                data_buffer_id=response.data_buffer_id + 1,
            ),
        )
        rejected_dbid = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(wrong_dbid_response),
        )
        self.assert_atomic_fault(
            rejected_dbid,
            accepted.state,
            "write_evict_copy_at_home_completion_correlation",
        )

        terminal_swap = ChiNetworkPacket.data(
            ChiCopyBackWrDataMessage(
                response.data_buffer_id,
                self.DATA,
                response=ChiRespCode.UC,
            ),
            source_id=self.RN,
            target_id=self.HOME,
        )
        rejected_swap = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(terminal_swap),
        )
        self.assert_atomic_fault(
            rejected_swap,
            accepted.state,
            "copyback_correlation",
        )

        acknowledged = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(response_packet),
        )
        ack_packet = acknowledged.emissions[0]
        ack = ack_packet.message
        self.assertIsInstance(ack, ChiCompAckMessage)
        self.assertEqual(response.data_buffer_id, ack.transaction_id)
        self.assertEqual(int(ChiRespCode.UC), ack.response)
        ack_expectation = (
            acknowledged.state.copyback_phase_ledger.for_data_buffer(
                self.RN,
                ack.transaction_id,
            )
        )
        self.assertIsNotNone(ack_expectation)
        assert ack_expectation is not None
        self.assertEqual(expectation.identity, ack_expectation.identity)
        self.assertIs(
            ChiCopyBackDeliveryPhase.REQUESTER_ACK,
            ack_expectation.phase,
        )
        self.assertEqual(ack_packet, ack_expectation.packet)

        rejected_ack_phase_swap = session.step(
            acknowledged.state,
            ChiDeliverCoherencePacket(terminal_swap),
        )
        self.assert_atomic_fault(
            rejected_ack_phase_swap,
            acknowledged.state,
            "copyback_correlation",
        )

        forged_dbid_ack = replace(
            ack_packet,
            message=replace(
                ack,
                transaction_id=ack.transaction_id + 1,
            ),
        )
        rejected_ack = session.step(
            acknowledged.state,
            ChiDeliverCoherencePacket(forged_dbid_ack),
        )
        self.assert_atomic_fault(
            rejected_ack,
            acknowledged.state,
            "completion_ack_correlation",
        )

        replayed_response = session.step(
            acknowledged.state,
            ChiDeliverCoherencePacket(response_packet),
        )
        self.assert_atomic_fault(
            replayed_response,
            acknowledged.state,
            "write_evict_copy_at_home_completion_correlation",
        )

        residency_before = acknowledged.state.home.clean_residency
        committed = self.apply(
            session,
            acknowledged.state,
            ChiDeliverCoherencePacket(ack_packet),
        )
        self.assertIs(
            residency_before,
            committed.state.home.clean_residency,
        )
        self.assert_final_clean_victim(
            session,
            initial,
            committed.state,
        )

        replayed_ack = session.step(
            committed.state,
            ChiDeliverCoherencePacket(ack_packet),
        )
        self.assert_atomic_fault(
            replayed_ack,
            committed.state,
            "completion_ack_correlation",
        )

    def test_clean_unique_snoop_cancels_delayed_cah_one_write_evict(
        self,
    ) -> None:
        for decision, current_copy in (
            (ChiCopyBackDecision.REQUEST_DATA, True),
            (ChiCopyBackDecision.COMPLETE_WITHOUT_DATA, True),
            (ChiCopyBackDecision.COMPLETE_WITHOUT_DATA, False),
        ):
            with self.subTest(
                decision=decision.value,
                current_copy=current_copy,
            ):
                session = self.build_multi_requester_session(
                    decision,
                    name=(
                        f"copy_at_home_snoop_{decision.value}_"
                        f"copy_{current_copy}"
                    ),
                    current_copy=current_copy,
                )
                initial = session.initial_state()
                request = ChiWriteEvictFullMessage(
                    self.WRITE_EVICT_TXN_ID,
                    self.ADDRESS,
                    copy_at_home=True,
                )
                write_evict_issued = self.apply(
                    session,
                    initial,
                    ChiSubmitWriteEvictFull(self.RN, request),
                )
                delayed_write_evict = write_evict_issued.emissions[0]
                frozen = write_evict_issued.state.request_nodes[
                    self.RN
                ].pending_copybacks[self.WRITE_EVICT_TXN_ID]
                self.assertEqual(request, frozen.request)
                self.assertTrue(frozen.request.copy_at_home)

                clean_unique_issued = self.apply(
                    session,
                    write_evict_issued.state,
                    ChiSubmitCleanUnique(
                        self.NEW_RN,
                        ChiCleanUniqueMessage(
                            self.WRITE_EVICT_TXN_ID + 1,
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
                old_owner_snooped = self.apply(
                    session,
                    clean_unique_at_home.state,
                    ChiDeliverCoherencePacket(snoop_packet),
                )
                old_state = old_owner_snooped.state.request_nodes[
                    self.RN
                ]
                old_line = old_state.line_at(self.ADDRESS)
                self.assertIsNotNone(old_line)
                assert old_line is not None
                self.assertIs(ChiCacheState.I, old_line.state)
                self.assertIsNone(old_line.data)
                self.assertFalse(old_line.copy_at_home)
                self.assertNotIn(
                    self.ADDRESS,
                    old_state.copy_at_home_lines,
                )
                pending = old_state.pending_copybacks[
                    self.WRITE_EVICT_TXN_ID
                ]
                self.assertEqual(request, pending.request)
                self.assertTrue(pending.request.copy_at_home)
                self.assertIs(
                    ChiRnCopyBackOutcome.CANCELED_I,
                    pending.outcome,
                )
                snoop_response = old_owner_snooped.emissions[0]
                self.assertIsInstance(
                    snoop_response.message,
                    ChiSnpRespMessage,
                )
                self.assertIs(
                    ChiRespCode.I,
                    snoop_response.message.response,
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
                home_after_snoop = clean_unique_retired.state.home
                self.assertEqual(
                    self.NEW_RN,
                    home_after_snoop.directory[
                        self.ADDRESS
                    ].unique_owner,
                )

                canceled_at_home = self.apply(
                    session,
                    clean_unique_retired.state,
                    ChiDeliverCoherencePacket(delayed_write_evict),
                )
                home_pending = next(
                    iter(
                        canceled_at_home.state.home
                        .pending_copybacks.values()
                    )
                )
                self.assertIs(
                    ChiHomeCopyBackAdmission.SNOOP_CANCELED,
                    home_pending.admission,
                )
                home_response = canceled_at_home.emissions[0]
                expectation = (
                    canceled_at_home.state.copyback_phase_ledger
                    .for_request(
                        self.RN,
                        self.WRITE_EVICT_TXN_ID,
                    )
                )
                self.assertIsNotNone(expectation)
                assert expectation is not None
                self.assertIs(
                    ChiCopyBackDeliveryPhase.HOME_RESPONSE,
                    expectation.phase,
                )
                self.assertEqual(home_response, expectation.packet)

                terminal_sent = self.apply(
                    session,
                    canceled_at_home.state,
                    ChiDeliverCoherencePacket(home_response),
                )
                terminal_packet = terminal_sent.emissions[0]
                terminal = terminal_packet.message
                expected_phase = (
                    ChiCopyBackDeliveryPhase.REQUESTER_DATA
                    if decision is ChiCopyBackDecision.REQUEST_DATA
                    else ChiCopyBackDeliveryPhase.REQUESTER_ACK
                )
                if decision is ChiCopyBackDecision.REQUEST_DATA:
                    self.assertIsInstance(
                        home_response.message,
                        ChiCompDBIDRespMessage,
                    )
                    self.assertIsInstance(
                        terminal,
                        ChiCopyBackWrDataMessage,
                    )
                    self.assertIs(ChiRespCode.I, terminal.response)
                    self.assertEqual(0, terminal.data)
                    self.assertEqual(0, terminal.byte_enable)
                else:
                    self.assertIsInstance(
                        home_response.message,
                        ChiCompMessage,
                    )
                    self.assertIsInstance(
                        terminal,
                        ChiCompAckMessage,
                    )
                    self.assertEqual(
                        int(ChiRespCode.I),
                        terminal.response,
                    )
                terminal_expectation = (
                    terminal_sent.state.copyback_phase_ledger
                    .for_data_buffer(
                        self.RN,
                        terminal.transaction_id,
                    )
                )
                self.assertIsNotNone(terminal_expectation)
                assert terminal_expectation is not None
                self.assertIs(
                    expected_phase,
                    terminal_expectation.phase,
                )
                self.assertEqual(
                    terminal_packet,
                    terminal_expectation.packet,
                )
                self.assertFalse(
                    terminal_sent.state.request_nodes[
                        self.RN
                    ].pending_copybacks
                )

                retired = self.apply(
                    session,
                    terminal_sent.state,
                    ChiDeliverCoherencePacket(terminal_packet),
                )
                self.assertEqual(
                    home_after_snoop.directory,
                    retired.state.home.directory,
                )
                self.assertEqual(
                    home_after_snoop.backing,
                    retired.state.home.backing,
                )
                self.assertEqual(
                    home_after_snoop.clean_residency,
                    retired.state.home.clean_residency,
                )
                self.assertFalse(
                    retired.state.home.pending_copybacks
                )
                self.assertFalse(
                    retired.state.copyback_phase_ledger.entries
                )
                self.assertTrue(session.is_quiescent(retired.state))

                replay = session.step(
                    retired.state,
                    ChiDeliverCoherencePacket(delayed_write_evict),
                )
                self.assert_atomic_fault(
                    replay,
                    retired.state,
                    "write_evict_admission_evidence",
                )

    def test_home_defers_same_line_request_until_cah_terminal(
        self,
    ) -> None:
        for decision in (
            ChiCopyBackDecision.REQUEST_DATA,
            ChiCopyBackDecision.COMPLETE_WITHOUT_DATA,
        ):
            with self.subTest(decision=decision.value):
                session = self.build_multi_requester_session(
                    decision,
                    name=f"copy_at_home_ordering_{decision.value}",
                )
                initial = session.initial_state()
                issued = self.apply(
                    session,
                    initial,
                    ChiSubmitWriteEvictFull(
                        self.RN,
                        ChiWriteEvictFullMessage(
                            self.WRITE_EVICT_TXN_ID,
                            self.ADDRESS,
                            copy_at_home=True,
                        ),
                    ),
                )
                accepted = self.apply(
                    session,
                    issued.state,
                    ChiDeliverCoherencePacket(issued.emissions[0]),
                )
                terminal_sent = self.apply(
                    session,
                    accepted.state,
                    ChiDeliverCoherencePacket(
                        accepted.emissions[0]
                    ),
                )

                clean_unique_issued = self.apply(
                    session,
                    terminal_sent.state,
                    ChiSubmitCleanUnique(
                        self.NEW_RN,
                        ChiCleanUniqueMessage(
                            self.WRITE_EVICT_TXN_ID + 1,
                            self.ADDRESS,
                        ),
                    ),
                )
                deferred = session.step(
                    clean_unique_issued.state,
                    ChiDeliverCoherencePacket(
                        clean_unique_issued.emissions[0]
                    ),
                )

                self.assertIsNone(deferred.fault)
                self.assertIsNotNone(deferred.blocked)
                assert deferred.blocked is not None
                self.assertIn(
                    "same-line",
                    deferred.blocked.reason,
                )
                self.assertIs(clean_unique_issued.state, deferred.state)
                self.assertFalse(deferred.emissions)

    def test_cached_provenance_survives_home_copy_loss_via_data_path(
        self,
    ) -> None:
        session = self.build_session(
            ChiCopyBackDecision.REQUEST_DATA,
            current_copy=False,
        )
        initial = session.initial_state()
        rn_line = initial.request_nodes[self.RN].line_at(self.ADDRESS)
        self.assertIsNotNone(rn_line)
        assert rn_line is not None
        self.assertTrue(rn_line.copy_at_home)
        self.assertIn(
            self.ADDRESS,
            initial.request_nodes[self.RN].copy_at_home_lines,
        )
        self.assertIsNone(
            initial.home.clean_residency.line_at(self.ADDRESS)
        )

        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(self.RN, request),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        response_packet = accepted.emissions[0]
        self.assertIsInstance(
            response_packet.message,
            ChiCompDBIDRespMessage,
        )
        response_expectation = (
            accepted.state.copyback_phase_ledger.for_request(
                self.RN,
                request.transaction_id,
            )
        )
        self.assertIsNotNone(response_expectation)
        assert response_expectation is not None
        self.assertIs(
            ChiCopyBackDeliveryPhase.HOME_RESPONSE,
            response_expectation.phase,
        )

        copied = self.apply(
            session,
            accepted.state,
            ChiDeliverCoherencePacket(response_packet),
        )
        copyback_packet = copied.emissions[0]
        self.assertIsInstance(
            copyback_packet.message,
            ChiCopyBackWrDataMessage,
        )
        data_expectation = (
            copied.state.copyback_phase_ledger.for_data_buffer(
                self.RN,
                copyback_packet.message.transaction_id,
            )
        )
        self.assertIsNotNone(data_expectation)
        assert data_expectation is not None
        self.assertIs(
            ChiCopyBackDeliveryPhase.REQUESTER_DATA,
            data_expectation.phase,
        )

        committed = self.apply(
            session,
            copied.state,
            ChiDeliverCoherencePacket(copyback_packet),
        )
        self.assert_final_clean_victim(
            session,
            initial,
            committed.state,
        )

    def test_home_copy_loss_rejects_no_data_policy_atomically(
        self,
    ) -> None:
        session = self.build_session(
            ChiCopyBackDecision.COMPLETE_WITHOUT_DATA,
            current_copy=False,
        )
        initial = session.initial_state()
        rn_line = initial.request_nodes[self.RN].line_at(self.ADDRESS)
        self.assertIsNotNone(rn_line)
        assert rn_line is not None
        self.assertTrue(rn_line.copy_at_home)
        self.assertIsNone(
            initial.home.clean_residency.line_at(self.ADDRESS)
        )

        request = ChiWriteEvictFullMessage(
            self.WRITE_EVICT_TXN_ID,
            self.ADDRESS,
            copy_at_home=True,
        )
        issued = self.apply(
            session,
            initial,
            ChiSubmitWriteEvictFull(self.RN, request),
        )
        rejected = session.step(
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        self.assert_atomic_fault(
            rejected,
            issued.state,
            "write_evict_copy_at_home_current_copy",
        )
        self.assertFalse(issued.state.home.pending_copybacks)
        self.assertFalse(
            issued.state.copyback_phase_ledger.entries
        )
        self.assertEqual(
            request,
            issued.state.request_nodes[self.RN]
            .pending_copybacks[request.transaction_id]
            .request,
        )
        self.assertIsNone(
            issued.state.home.clean_residency.line_at(self.ADDRESS)
        )

    def test_session_acquires_cah_one_on_comp_data_then_uses_it(
        self,
    ) -> None:
        session = self.build_session(
            ChiCopyBackDecision.COMPLETE_WITHOUT_DATA,
            resident=False,
            initial_owner=False,
        )
        initial = session.initial_state()
        read_request = ChiReadUniqueMessage(
            self.READ_TXN_ID,
            self.ADDRESS,
        )

        read_issued = self.apply(
            session,
            initial,
            ChiSubmitCoherentRead(self.RN, read_request),
        )
        read_at_home = self.apply(
            session,
            read_issued.state,
            ChiDeliverCoherencePacket(read_issued.emissions[0]),
        )
        completion_packet = read_at_home.emissions[0]
        completion = completion_packet.message
        self.assertIsInstance(completion, ChiCompDataMessage)
        self.assertTrue(completion.copy_at_home)
        self.assertIs(ChiRespCode.UC, completion.response)
        self.assertEqual(self.DATA, completion.data)

        read_at_rn = self.apply(
            session,
            read_at_home.state,
            ChiDeliverCoherencePacket(completion_packet),
        )
        line = read_at_rn.state.request_nodes[self.RN].line_at(
            self.ADDRESS
        )
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIs(ChiCacheState.UC, line.state)
        self.assertTrue(line.copy_at_home)
        self.assertIn(
            self.ADDRESS,
            read_at_rn.state.request_nodes[
                self.RN
            ].copy_at_home_lines,
        )

        read_retired = self.apply(
            session,
            read_at_rn.state,
            ChiDeliverCoherencePacket(read_at_rn.emissions[0]),
        )
        self.assertTrue(session.is_quiescent(read_retired.state))
        self.assertEqual(
            self.RN,
            read_retired.state.home.directory[
                self.ADDRESS
            ].unique_owner,
        )
        self.assertEqual(
            self.DATA,
            read_retired.state.home.clean_residency.line_at(
                self.ADDRESS
            ).data,
        )

        write_issued = self.apply(
            session,
            read_retired.state,
            ChiSubmitWriteEvictFull(
                self.RN,
                ChiWriteEvictFullMessage(
                    self.WRITE_EVICT_TXN_ID,
                    self.ADDRESS,
                    copy_at_home=True,
                ),
            ),
        )
        write_at_home = self.apply(
            session,
            write_issued.state,
            ChiDeliverCoherencePacket(write_issued.emissions[0]),
        )
        self.assertIsInstance(
            write_at_home.emissions[0].message,
            ChiCompMessage,
        )
        write_at_rn = self.apply(
            session,
            write_at_home.state,
            ChiDeliverCoherencePacket(write_at_home.emissions[0]),
        )
        retired = self.apply(
            session,
            write_at_rn.state,
            ChiDeliverCoherencePacket(write_at_rn.emissions[0]),
        )

        self.assert_final_clean_victim(
            session,
            initial,
            retired.state,
        )

    def test_resolved_network_acquires_and_consumes_copy_at_home(
        self,
    ) -> None:
        cases = (
            (
                ChiCopyBackDecision.REQUEST_DATA,
                (
                    ChiWriteEvictFullMessage,
                    ChiCompDBIDRespMessage,
                    ChiCopyBackWrDataMessage,
                ),
                (
                    ChiChannelKind.REQ,
                    ChiChannelKind.RSP,
                    ChiChannelKind.DAT,
                ),
            ),
            (
                ChiCopyBackDecision.COMPLETE_WITHOUT_DATA,
                (
                    ChiWriteEvictFullMessage,
                    ChiCompMessage,
                    ChiCompAckMessage,
                ),
                (
                    ChiChannelKind.REQ,
                    ChiChannelKind.RSP,
                    ChiChannelKind.RSP,
                ),
            ),
        )
        for decision, write_types, write_channels in cases:
            with self.subTest(decision=decision):
                resolved = self.build_resolved_network(decision)
                self.assertTrue(resolved.is_closed)
                for feature in self.FEATURES:
                    resolved.capabilities.require(feature)

                modifier_evidence = resolved.capabilities.require(
                    CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME
                )
                self.assertEqual(
                    ("hn_to_rn",),
                    modifier_evidence.flows[
                        "write_evict_copy_at_home_response"
                    ].connections,
                )
                self.assertEqual(
                    ("rn_to_hn",),
                    modifier_evidence.flows[
                        "write_evict_copy_at_home_completion_ack"
                    ].connections,
                )

                session = ChiCoherenceNetworkSession.from_resolved(
                    resolved
                )
                initial = session.initial_state()
                read_issued = self.apply(
                    session,
                    initial,
                    ChiSubmitCoherentRead(
                        self.RN,
                        ChiReadUniqueMessage(
                            self.READ_TXN_ID,
                            self.ADDRESS,
                        ),
                    ),
                )
                read_run = session.run_until_quiescent(
                    read_issued.state,
                    max_steps=256,
                )
                self.assertIs(Verdict.PASS, read_run.verdict)
                self.assertIsNone(read_run.blocked)
                self.assertTrue(
                    session.is_quiescent(read_run.final_state)
                )

                read_events = tuple(
                    event
                    for event in read_run.emissions
                    if event.kind
                    is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
                )
                self.assertEqual(3, len(read_events))
                read_packets = tuple(
                    event.packet for event in read_events
                )
                self.assertTrue(
                    all(packet is not None for packet in read_packets)
                )
                self.assertEqual(
                    (
                        ChiReadUniqueMessage,
                        ChiCompDataMessage,
                        ChiCompAckMessage,
                    ),
                    tuple(
                        type(packet.message)
                        for packet in read_packets
                        if packet is not None
                    ),
                )
                self.assertEqual(
                    (
                        ChiChannelKind.REQ,
                        ChiChannelKind.DAT,
                        ChiChannelKind.RSP,
                    ),
                    tuple(
                        packet.channel
                        for packet in read_packets
                        if packet is not None
                    ),
                )
                completion_packet = read_packets[1]
                assert completion_packet is not None
                completion = completion_packet.message
                self.assertIsInstance(completion, ChiCompDataMessage)
                self.assertTrue(completion.copy_at_home)
                self.assertEqual(self.DATA, completion.data)

                acquired = read_run.final_state.coherence
                acquired_line = acquired.request_nodes[
                    self.RN
                ].line_at(self.ADDRESS)
                self.assertIsNotNone(acquired_line)
                assert acquired_line is not None
                self.assertIs(ChiCacheState.UC, acquired_line.state)
                self.assertTrue(acquired_line.copy_at_home)
                self.assertEqual(
                    self.RN,
                    acquired.home.directory[
                        self.ADDRESS
                    ].unique_owner,
                )

                write_issued = self.apply(
                    session,
                    read_run.final_state,
                    ChiSubmitWriteEvictFull(
                        self.RN,
                        ChiWriteEvictFullMessage(
                            self.WRITE_EVICT_TXN_ID,
                            self.ADDRESS,
                            copy_at_home=True,
                        ),
                    ),
                )
                write_run = session.run_until_quiescent(
                    write_issued.state,
                    max_steps=256,
                )
                self.assertIs(Verdict.PASS, write_run.verdict)
                self.assertIsNone(write_run.blocked)
                self.assertTrue(
                    session.is_quiescent(write_run.final_state)
                )

                write_events = tuple(
                    event
                    for event in write_run.emissions
                    if event.kind
                    is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
                )
                self.assertEqual(3, len(write_events))
                write_packets = tuple(
                    event.packet for event in write_events
                )
                self.assertTrue(
                    all(packet is not None for packet in write_packets)
                )
                self.assertEqual(
                    write_types,
                    tuple(
                        type(packet.message)
                        for packet in write_packets
                        if packet is not None
                    ),
                )
                self.assertEqual(
                    write_channels,
                    tuple(
                        packet.channel
                        for packet in write_packets
                        if packet is not None
                    ),
                )

                route_expectations = (
                    (write_events[0], "rn_to_hn@"),
                    (write_events[1], "hn_to_rn@"),
                    (write_events[2], "rn_to_hn@"),
                )
                for event, prefix in route_expectations:
                    self.assertTrue(
                        any(
                            item.startswith(prefix)
                            for item in event.lineage
                        ),
                        (prefix, event.lineage),
                    )

                self.assert_final_clean_victim(
                    session.coherence,
                    initial.coherence,
                    write_run.final_state.coherence,
                )


if __name__ == "__main__":
    unittest.main()
