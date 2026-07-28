from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    bind_chi_issue_h_home_vdut,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_EVICT_HOME_CAPABILITIES,
    CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
    ChiCacheLine,
    ChiCacheState,
    ChiHomeDirectoryEntry,
    ChiParticipantCapability,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompMessage,
    ChiEvictMessage,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiRespCode,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_EVICT,
    CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiLineRelease,
    ChiSubmitEvict,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
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
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHCleanEvictNetworkTest(unittest.TestCase):
    REQUESTER = 0x07
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xE71C7

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
        channel: ChiChannelKind,
    ) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=(
                ChiReqChannelProfile(
                    ChiIssueHReqProfile(),
                    (1,),
                    f"{name}.req",
                )
                if channel is ChiChannelKind.REQ
                else None
            ),
            response=(
                ChiRspChannelProfile(
                    ChiIssueHRspProfile(),
                    1,
                    f"{name}.rsp",
                )
                if channel is ChiChannelKind.RSP
                else None
            ),
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    def build_resolved(self):
        builder = SystemProtocolBuilder("chi_clean_evict_direct")
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_req": self.port(
                        "tx_req",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_rsp": self.port(
                        "rx_rsp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "hn0",
                {
                    "rx_req": self.port(
                        "rx_req",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_rsp": self.port(
                        "tx_rsp",
                        TransportDirection.TRANSMIT,
                    ),
                },
            )
        )
        builder.connect_transport(
            "evict_request",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("rn0", "tx_req"),
            VirtualDutPortRef("hn0", "rx_req"),
            profile=self.link_profile(
                "evict_request",
                ChiChannelKind.REQ,
            ),
        )
        builder.connect_transport(
            "evict_completion",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("hn0", "tx_rsp"),
            VirtualDutPortRef("rn0", "rx_rsp"),
            profile=self.link_profile(
                "evict_completion",
                ChiChannelKind.RSP,
            ),
        )

        claim_name = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                claim_name,
                VirtualDutPortRef("hn0", "rx_req"),
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
                "tx_req": frozenset((ChiChannelKind.REQ,)),
                "rx_rsp": frozenset((ChiChannelKind.RSP,)),
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
        home = bind_chi_issue_h_home_vdut(
            duts["hn0"],
            backing_core,
            self.HOME,
            port_channels={
                "rx_req": frozenset((ChiChannelKind.REQ,)),
                "tx_rsp": frozenset((ChiChannelKind.RSP,)),
            },
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    unique_owner=self.REQUESTER,
                ),
            ),
            participant_name="home",
            binding_name="hn0",
        )

        resolved = resolve_chi_system(
            system,
            facets=(
                requester.facets.facets[0],
                home.facets.facets[0],
            ),
            feature_contract=ChiFeatureContract(
                {"requester": "rn0"},
                frozenset((CHI_FEATURE_CLEAN_EVICT,)),
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
                    CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES,
                ),
                ChiParticipantCapability(
                    "hn0",
                    CHI_CLEAN_EVICT_HOME_CAPABILITIES,
                ),
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_EVICT_LIFECYCLE,)
            ),
        )
        return resolved

    def test_clean_evict_closes_and_runs_req_rsp_only(self) -> None:
        resolved = self.build_resolved()

        self.assertTrue(resolved.is_closed)
        evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_EVICT
        )
        self.assertEqual(
            ("evict_request",),
            evidence.flows["evict_request"].connections,
        )
        self.assertEqual(
            ("evict_completion",),
            evidence.flows["evict_completion"].connections,
        )

        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        initial = session.initial_state()
        initial_backing = initial.coherence.home.backing.line_at(
            self.ADDRESS
        )
        self.assertIsNotNone(initial_backing)
        assert initial_backing is not None

        issued = session.step(
            initial,
            ChiSubmitEvict(
                self.REQUESTER,
                ChiEvictMessage(0x31, self.ADDRESS),
            ),
        )
        self.assertIsNone(issued.fault)
        self.assertIsNone(issued.blocked)
        issued_progress = session.project_progress(issued.state)
        self.assertEqual(1, len(issued_progress.held))
        held = issued_progress.held[0]
        self.assertEqual(self.REQUESTER, held.holder_node_id)
        self.assertEqual(self.ADDRESS, held.address)
        self.assertIs(ChiLineRelease.COMP, held.release_on)
        self.assertEqual(0x31, held.release_transaction_id)
        self.assertEqual((), issued_progress.waiting)

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
        self.assertEqual(2, len(endpoint_events))
        packets = tuple(event.packet for event in endpoint_events)
        self.assertTrue(all(packet is not None for packet in packets))
        request_packet, completion_packet = packets
        assert request_packet is not None
        assert completion_packet is not None

        self.assertEqual(
            (ChiEvictMessage, ChiCompMessage),
            (
                type(request_packet.message),
                type(completion_packet.message),
            ),
        )
        self.assertEqual(
            (ChiChannelKind.REQ, ChiChannelKind.RSP),
            (request_packet.channel, completion_packet.channel),
        )
        self.assertFalse(
            any(
                packet.channel
                in (ChiChannelKind.SNP, ChiChannelKind.DAT)
                for packet in (request_packet, completion_packet)
            )
        )
        self.assertFalse(
            any(
                isinstance(packet.message, ChiCompAckMessage)
                for packet in (request_packet, completion_packet)
            )
        )
        completion = completion_packet.message
        assert isinstance(completion, ChiCompMessage)
        self.assertEqual(0x31, completion.transaction_id)
        self.assertIs(ChiRespCode.I, completion.response)
        self.assertEqual(0, completion.data_buffer_id)

        final = run.final_state.coherence
        requester = final.request_nodes[self.REQUESTER]
        requester_line = requester.line_at(self.ADDRESS)
        self.assertIsNotNone(requester_line)
        assert requester_line is not None
        self.assertIs(ChiCacheState.I, requester_line.state)
        self.assertIsNone(requester_line.data)
        self.assertNotIn(self.ADDRESS, requester.cache.lines)
        self.assertFalse(requester.pending_transactions)

        directory = final.home.directory[self.ADDRESS]
        self.assertIsNone(directory.unique_owner)
        self.assertFalse(directory.sharers)
        self.assertIsNone(directory.shared_dirty_owner)
        self.assertFalse(final.home.pending)
        final_backing = final.home.backing.line_at(self.ADDRESS)
        self.assertIsNotNone(final_backing)
        assert final_backing is not None
        self.assertEqual(initial_backing.data, final_backing.data)
        self.assertEqual(initial_backing.version, final_backing.version)

        progress = session.project_progress(run.final_state)
        self.assertEqual((), progress.held)
        self.assertEqual((), progress.waiting)


if __name__ == "__main__":
    unittest.main()
