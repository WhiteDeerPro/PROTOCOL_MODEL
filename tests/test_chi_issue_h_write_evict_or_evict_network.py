from __future__ import annotations

from dataclasses import replace
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    bind_chi_issue_h_home_vdut,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_WRITE_EVICT_OR_EVICT_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_OR_EVICT_REQUESTER_CAPABILITIES,
    ChiCacheLine,
    ChiCacheState,
    ChiHomeDirectoryEntry,
    ChiParticipantCapability,
    ChiWriteEvictOrEvictDecision,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiCopyBackWrDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiNetworkPacket,
    ChiRespCode,
    ChiWriteEvictOrEvictMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_WRITE_EVICT_OR_EVICT,
    CHI_SYSTEM_WRITE_EVICT_OR_EVICT_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
    ChiDeliverCoherencePacket,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiLineRelease,
    ChiSubmitWriteEvictOrEvict,
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


class ChiIssueHWriteEvictOrEvictNetworkTest(unittest.TestCase):
    REQUESTER = 0x07
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xE71C7
    TXN_ID = 0x42
    DBID = 0x200

    def apply(self, component, state, action):
        transition = component.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def assert_atomic_fault(
        self,
        transition,
        state,
        suffix: str,
    ) -> None:
        self.assertIsNotNone(transition.fault)
        self.assertTrue(transition.fault.rule.endswith(suffix))
        self.assertIs(state, transition.state)
        self.assertFalse(transition.emissions)

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
        decision: ChiWriteEvictOrEvictDecision,
        initial_state: ChiCacheState,
    ):
        builder = SystemProtocolBuilder(
            "chi_write_evict_or_evict_direct"
        )
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx": self.port(
                        "tx",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx": self.port(
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
                    "rx": self.port(
                        "rx",
                        TransportDirection.RECEIVE,
                    ),
                    "tx": self.port(
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
        home_to_requester = frozenset((ChiChannelKind.RSP,))
        builder.connect_transport(
            "rn_to_hn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("rn0", "tx"),
            VirtualDutPortRef("hn0", "rx"),
            profile=self.link_profile(
                "rn_to_hn",
                requester_to_home,
            ),
        )
        builder.connect_transport(
            "hn_to_rn",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("hn0", "tx"),
            VirtualDutPortRef("rn0", "rx"),
            profile=self.link_profile(
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
            self.REQUESTER,
            self.HOME,
            port_channels={
                "tx": requester_to_home,
                "rx": home_to_requester,
            },
            initial_lines=(
                ChiCacheLine(
                    self.ADDRESS,
                    initial_state,
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
                "rx": requester_to_home,
                "tx": home_to_requester,
            },
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=(
                        self.REQUESTER
                        if initial_state is ChiCacheState.UC
                        else None
                    ),
                    sharers=(
                        frozenset((self.REQUESTER,))
                        if initial_state is ChiCacheState.SC
                        else frozenset()
                    ),
                ),
            ),
            clean_residency_core=clean_residency_core,
            participant_name="home",
            binding_name="hn0",
            initial_data_buffer_id=self.DBID,
            write_evict_or_evict_policy=(
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
                frozenset((CHI_FEATURE_WRITE_EVICT_OR_EVICT,)),
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
                    CHI_WRITE_EVICT_OR_EVICT_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_WRITE_EVICT_OR_EVICT_HOME_CAPABILITIES,
                ),
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_WRITE_EVICT_OR_EVICT_LIFECYCLE,)
            ),
        )

    def start_system_outcome(
        self,
        decision: ChiWriteEvictOrEvictDecision,
    ):
        session = ChiCoherenceSession.from_resolved(
            self.build_resolved(decision, ChiCacheState.UC)
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitWriteEvictOrEvict(
                self.REQUESTER,
                ChiWriteEvictOrEvictMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                    likely_shared=False,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )
        return session, accepted

    def test_system_rejects_request_replay_after_home_outcome(
        self,
    ) -> None:
        session = ChiCoherenceSession.from_resolved(
            self.build_resolved(
                ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                ChiCacheState.UC,
            )
        )
        issued = self.apply(
            session,
            session.initial_state(),
            ChiSubmitWriteEvictOrEvict(
                self.REQUESTER,
                ChiWriteEvictOrEvictMessage(
                    self.TXN_ID,
                    self.ADDRESS,
                    likely_shared=False,
                ),
            ),
        )
        accepted = self.apply(
            session,
            issued.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        replayed = session.step(
            accepted.state,
            ChiDeliverCoherencePacket(issued.emissions[0]),
        )

        self.assert_atomic_fault(
            replayed,
            accepted.state,
            "write_evict_or_evict_request_replay",
        )

    def test_system_rejects_interchanged_home_outcomes_atomically(
        self,
    ) -> None:
        cases = (
            (
                ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                ChiCompMessage(
                    self.TXN_ID,
                    self.DBID,
                    response=ChiRespCode.I,
                ),
                "write_evict_or_evict_completion_correlation",
            ),
            (
                ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
                ChiCompDBIDRespMessage(
                    self.TXN_ID,
                    self.DBID,
                ),
                "write_evict_or_evict_response_correlation",
            ),
        )
        for decision, wrong_message, rule in cases:
            with self.subTest(decision=decision.value):
                session, accepted = self.start_system_outcome(decision)
                rejected = session.step(
                    accepted.state,
                    ChiDeliverCoherencePacket(
                        ChiNetworkPacket.response(
                            wrong_message,
                            source_id=self.HOME,
                            target_id=self.REQUESTER,
                        )
                    ),
                )

                self.assert_atomic_fault(
                    rejected,
                    accepted.state,
                    rule,
                )
                self.assertEqual(
                    accepted.emissions[0],
                    accepted.state
                    .expected_write_evict_or_evict_responses[
                        (self.REQUESTER, self.TXN_ID)
                    ],
                )

    def test_system_rejects_forged_dbid_and_replayed_evidence(
        self,
    ) -> None:
        cases = (
            (
                ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                "write_evict_or_evict_response_correlation",
                "copyback_correlation",
            ),
            (
                ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
                "write_evict_or_evict_completion_correlation",
                "completion_ack_correlation",
            ),
        )
        for decision, response_rule, terminal_rule in cases:
            with self.subTest(decision=decision.value):
                session, accepted = self.start_system_outcome(decision)
                response_packet = accepted.emissions[0]
                forged_response = replace(
                    response_packet,
                    message=replace(
                        response_packet.message,
                        data_buffer_id=self.DBID + 1,
                    ),
                )
                rejected_forge = session.step(
                    accepted.state,
                    ChiDeliverCoherencePacket(forged_response),
                )
                self.assert_atomic_fault(
                    rejected_forge,
                    accepted.state,
                    response_rule,
                )

                responded = self.apply(
                    session,
                    accepted.state,
                    ChiDeliverCoherencePacket(response_packet),
                )
                terminal_packet = responded.emissions[0]
                rejected_response_replay = session.step(
                    responded.state,
                    ChiDeliverCoherencePacket(response_packet),
                )
                self.assert_atomic_fault(
                    rejected_response_replay,
                    responded.state,
                    response_rule,
                )

                retired = self.apply(
                    session,
                    responded.state,
                    ChiDeliverCoherencePacket(terminal_packet),
                )
                rejected_terminal_replay = session.step(
                    retired.state,
                    ChiDeliverCoherencePacket(terminal_packet),
                )
                self.assert_atomic_fault(
                    rejected_terminal_replay,
                    retired.state,
                    terminal_rule,
                )
                self.assertTrue(session.is_quiescent(retired.state))

    def test_resolved_network_runs_both_three_packet_outcomes(
        self,
    ) -> None:
        cases = (
            (
                ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                ChiCacheState.UC,
                False,
                (
                    ChiWriteEvictOrEvictMessage,
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
                ChiWriteEvictOrEvictDecision.REQUEST_DATA,
                ChiCacheState.SC,
                True,
                (
                    ChiWriteEvictOrEvictMessage,
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
                ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
                ChiCacheState.UC,
                False,
                (
                    ChiWriteEvictOrEvictMessage,
                    ChiCompMessage,
                    ChiCompAckMessage,
                ),
                (
                    ChiChannelKind.REQ,
                    ChiChannelKind.RSP,
                    ChiChannelKind.RSP,
                ),
            ),
            (
                ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA,
                ChiCacheState.SC,
                True,
                (
                    ChiWriteEvictOrEvictMessage,
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
        for (
            decision,
            initial_state,
            likely_shared,
            expected_types,
            expected_channels,
        ) in cases:
            with self.subTest(
                decision=decision.value,
                initial_state=initial_state.value,
            ):
                resolved = self.build_resolved(decision, initial_state)
                self.assertTrue(resolved.is_closed)
                evidence = resolved.capabilities.require(
                    CHI_FEATURE_WRITE_EVICT_OR_EVICT
                )
                self.assertEqual(
                    {
                        "write_evict_or_evict_request",
                        "write_evict_or_evict_response",
                        "write_evict_or_evict_copyback_data",
                        "write_evict_or_evict_completion_ack",
                    },
                    set(evidence.flows),
                )
                self.assertEqual(
                    ("rn_to_hn",),
                    evidence.flows[
                        "write_evict_or_evict_request"
                    ].connections,
                )
                self.assertEqual(
                    ("hn_to_rn",),
                    evidence.flows[
                        "write_evict_or_evict_response"
                    ].connections,
                )
                for flow_name in (
                    "write_evict_or_evict_copyback_data",
                    "write_evict_or_evict_completion_ack",
                ):
                    self.assertEqual(
                        ("rn_to_hn",),
                        evidence.flows[flow_name].connections,
                    )

                session = ChiCoherenceNetworkSession.from_resolved(
                    resolved
                )
                initial = session.initial_state()
                initial_backing = (
                    initial.coherence.home.backing.line_at(
                        self.ADDRESS
                    )
                )
                self.assertIsNotNone(initial_backing)
                issued = session.step(
                    initial,
                    ChiSubmitWriteEvictOrEvict(
                        self.REQUESTER,
                        ChiWriteEvictOrEvictMessage(
                            self.TXN_ID,
                            self.ADDRESS,
                            likely_shared=likely_shared,
                        ),
                    ),
                )
                self.assertIsNone(issued.fault)
                self.assertIsNone(issued.blocked)
                requester_holders = tuple(
                    held
                    for held in session.project_progress(
                        issued.state
                    ).held
                    if held.holder_node_id == self.REQUESTER
                )
                self.assertEqual(1, len(requester_holders))
                self.assertIs(
                    ChiLineRelease.COMP_OR_COMP_DBID_RESP,
                    requester_holders[0].release_on,
                )

                run = session.run_until_quiescent(
                    issued.state,
                    max_steps=256,
                )

                self.assertIs(Verdict.PASS, run.verdict)
                self.assertIsNone(run.blocked)
                self.assertTrue(
                    session.is_quiescent(run.final_state)
                )
                endpoint_events = tuple(
                    event
                    for event in run.emissions
                    if event.kind
                    is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
                )
                self.assertEqual(3, len(endpoint_events))
                packets = tuple(
                    event.packet for event in endpoint_events
                )
                self.assertTrue(
                    all(packet is not None for packet in packets)
                )
                self.assertEqual(
                    expected_types,
                    tuple(type(packet.message) for packet in packets),
                )
                self.assertEqual(
                    expected_channels,
                    tuple(packet.channel for packet in packets),
                )
                self.assertNotIn(
                    ChiChannelKind.SNP,
                    tuple(packet.channel for packet in packets),
                )
                for event, route_name in zip(
                    endpoint_events,
                    ("rn_to_hn", "hn_to_rn", "rn_to_hn"),
                    strict=True,
                ):
                    self.assertTrue(
                        any(
                            item.startswith(f"{route_name}@")
                            for item in event.lineage
                        ),
                        event.lineage,
                    )

                request_packet, response_packet, final_packet = packets
                assert request_packet is not None
                assert response_packet is not None
                assert final_packet is not None
                response = response_packet.message
                final_message = final_packet.message
                self.assertEqual(
                    self.TXN_ID,
                    response.transaction_id,
                )
                self.assertEqual(
                    response.data_buffer_id,
                    final_message.transaction_id,
                )

                final = run.final_state.coherence
                rn_state = final.request_nodes[self.REQUESTER]
                line = rn_state.line_at(self.ADDRESS)
                self.assertIsNotNone(line)
                assert line is not None
                self.assertIs(ChiCacheState.I, line.state)
                self.assertIsNone(line.data)
                self.assertNotIn(self.ADDRESS, rn_state.cache.lines)
                self.assertFalse(rn_state.pending_copybacks)

                directory = final.home.directory[self.ADDRESS]
                self.assertIsNone(directory.unique_owner)
                self.assertIsNone(directory.shared_dirty_owner)
                self.assertFalse(directory.sharers)
                final_backing = final.home.backing.line_at(
                    self.ADDRESS
                )
                self.assertEqual(initial_backing, final_backing)
                self.assertEqual(
                    initial_backing.version,
                    final_backing.version,
                )
                self.assertFalse(final.home.pending_copybacks)

                resident = final.home.clean_residency.line_at(
                    self.ADDRESS
                )
                if (
                    decision
                    is ChiWriteEvictOrEvictDecision.REQUEST_DATA
                ):
                    self.assertIsInstance(
                        final_message,
                        ChiCopyBackWrDataMessage,
                    )
                    self.assertIs(
                        (
                            ChiRespCode.UC
                            if initial_state is ChiCacheState.UC
                            else ChiRespCode.SC
                        ),
                        final_message.response,
                    )
                    self.assertEqual(self.DATA, final_message.data)
                    self.assertEqual(
                        (1 << 64) - 1,
                        final_message.byte_enable,
                    )
                    self.assertIsInstance(
                        resident,
                        CacheLinePayload,
                    )
                    self.assertEqual(self.DATA, resident.data)
                    self.assertFalse(
                        any(
                            isinstance(
                                packet.message,
                                ChiCompAckMessage,
                            )
                            for packet in packets
                        )
                    )
                else:
                    self.assertIsInstance(
                        response,
                        ChiCompMessage,
                    )
                    self.assertIs(ChiRespCode.I, response.response)
                    self.assertIsInstance(
                        final_message,
                        ChiCompAckMessage,
                    )
                    self.assertIsNone(resident)
                    self.assertNotIn(
                        ChiChannelKind.DAT,
                        tuple(
                            packet.channel for packet in packets
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
