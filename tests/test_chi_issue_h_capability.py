from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES,
    CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
    CHI_READ_NO_SNP_HOME_CAPABILITIES,
    CHI_READ_NO_SNP_REQUESTER_CAPABILITIES,
    CHI_REQUEST_RETRY_HOME_CAPABILITIES,
    CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
    ChiCapabilityKey,
    ChiDirectHomeNode,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.participants.capability import (
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES,
    CHI_HOME_PASS_DIRTY_MEMORY_UPDATE,
)
from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_BUILTIN_FEATURE_CATALOG,
    CHI_CLEAN_READ_UNIQUE_DEFINITION,
    CHI_CLEAN_READ_UNIQUE_RETRY_DEFINITION,
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_FEATURE_READ_NO_SNP,
    CHI_FEATURE_REQUEST_RETRY,
    CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,
    CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
    ChiCapabilityClosureError,
    ChiCapabilityGapKind,
    ChiFeatureCatalog,
    ChiFeatureContract,
    ChiFeatureDefinition,
    ChiFeatureKey,
    ChiFlowCapability,
    ChiFlowRequirement,
    ChiFlowProjectionGapKind,
    ChiRoleRequirement,
    ChiTransportNetworkSession,
    bind_chi_flow_requirement,
    project_chi_flow_capabilities,
    resolve_chi_capabilities,
    resolve_projected_chi_capabilities,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION,
    CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
    CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.system import (
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHCapabilityClosureTest(unittest.TestCase):
    @staticmethod
    def contract(*required):
        return ChiFeatureContract(
            {"requester": "rn0", "home": "hn0"},
            frozenset(required),
        )

    @staticmethod
    def participants(*, retry: bool):
        requester = (
            CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES
            if retry
            else CHI_READ_NO_SNP_REQUESTER_CAPABILITIES
        )
        home = (
            CHI_REQUEST_RETRY_HOME_CAPABILITIES
            if retry
            else CHI_READ_NO_SNP_HOME_CAPABILITIES
        )
        return (
            ChiParticipantCapability("rn0", requester),
            ChiParticipantCapability("hn0", home),
        )

    @staticmethod
    def flows(*, response: bool = True):
        flows = [
            ChiFlowCapability(
                "request_path",
                "rn0",
                "hn0",
                ChiChannelKind.REQ,
                connections=("rn_req", "xp_req", "hn_req"),
            ),
            ChiFlowCapability(
                "data_path",
                "hn0",
                "rn0",
                ChiChannelKind.DAT,
                connections=("hn_dat", "xp_dat", "rn_dat"),
            ),
        ]
        if response:
            flows.append(
                ChiFlowCapability(
                    "response_path",
                    "hn0",
                    "rn0",
                    ChiChannelKind.RSP,
                    connections=("hn_rsp", "xp_rsp", "rn_rsp"),
                )
            )
        return tuple(flows)

    def test_builtin_read_and_retry_close_with_explicit_evidence(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(
                CHI_FEATURE_READ_NO_SNP,
                CHI_FEATURE_REQUEST_RETRY,
            ),
            participants=self.participants(retry=True),
            flows=self.flows(),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_READ_NO_SNP))
        self.assertTrue(resolved.supports(CHI_FEATURE_REQUEST_RETRY))
        self.assertEqual((), resolved.gaps(CHI_FEATURE_READ_NO_SNP))
        self.assertEqual((), resolved.gaps(CHI_FEATURE_REQUEST_RETRY))
        retry = resolved.require(CHI_FEATURE_REQUEST_RETRY)
        self.assertEqual(
            ("hn_rsp", "xp_rsp", "rn_rsp"),
            retry.flows["retry_response"].connections,
        )
        self.assertIs(resolved, resolved.require_contract())

    def test_missing_response_path_removes_retry_but_not_base_read(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(CHI_FEATURE_REQUEST_RETRY),
            participants=self.participants(retry=True),
            flows=self.flows(response=False),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_READ_NO_SNP))
        self.assertFalse(resolved.supports(CHI_FEATURE_REQUEST_RETRY))
        gaps = resolved.gaps(CHI_FEATURE_REQUEST_RETRY)
        self.assertEqual(1, len(gaps))
        self.assertIs(ChiCapabilityGapKind.FLOW, gaps[0].kind)
        self.assertIn("no RSP path", gaps[0].reason)
        with self.assertRaises(ChiCapabilityClosureError):
            resolved.require(CHI_FEATURE_REQUEST_RETRY)
        with self.assertRaises(ChiCapabilityClosureError):
            resolved.require_contract()

    def test_participant_gap_reports_missing_atomic_capabilities(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(CHI_FEATURE_REQUEST_RETRY),
            participants=self.participants(retry=False),
            flows=self.flows(),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_READ_NO_SNP))
        gaps = resolved.gaps(CHI_FEATURE_REQUEST_RETRY)
        self.assertEqual(
            {ChiCapabilityGapKind.PARTICIPANT},
            {gap.kind for gap in gaps},
        )
        self.assertEqual({"rn0", "hn0"}, {gap.subject for gap in gaps})
        self.assertTrue(all(gap.missing for gap in gaps))

    def test_catalog_extension_is_explicit_and_does_not_mutate_builtin(self) -> None:
        custom_key = ChiFeatureKey("chi.feature.vendor.trace")
        trace = ChiCapabilityKey("chi.requester.vendor_trace")
        custom = ChiFeatureDefinition(
            custom_key,
            roles=(
                ChiRoleRequirement("requester", frozenset((trace,))),
            ),
        )

        extended = CHI_BUILTIN_FEATURE_CATALOG.extend(custom)

        self.assertNotIn(
            custom_key, CHI_BUILTIN_FEATURE_CATALOG.definitions
        )
        self.assertIn(custom_key, extended.definitions)
        with self.assertRaises(TypeError):
            extended.definitions[custom_key] = custom


class ChiIssueHCleanReadSharedCapabilityTest(unittest.TestCase):
    @staticmethod
    def contract():
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
                "snoopee": "rn1",
            },
            frozenset((CHI_FEATURE_CLEAN_READ_SHARED,)),
        )

    @staticmethod
    def participants():
        return (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "rn1",
                CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES,
            ),
        )

    @staticmethod
    def flows(*, omit: frozenset[str] = frozenset()):
        definitions = (
            ("request", "rn0", "hn0", ChiChannelKind.REQ),
            ("snoop", "hn0", "rn1", ChiChannelKind.SNP),
            ("snoop_response", "rn1", "hn0", ChiChannelKind.RSP),
            ("completion_data", "hn0", "rn0", ChiChannelKind.DAT),
            ("completion_ack", "rn0", "hn0", ChiChannelKind.RSP),
        )
        return tuple(
            ChiFlowCapability(name, source, target, channel)
            for name, source, target, channel in definitions
            if name not in omit
        )

    def test_clean_read_shared_closes_three_roles_and_five_flows(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE,)
            ),
        )

        evidence = resolved.require(CHI_FEATURE_CLEAN_READ_SHARED)
        self.assertEqual(
            {"requester", "home", "snoopee"},
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "request",
                "snoop",
                "snoop_response",
                "completion_data",
                "completion_ack",
            },
            set(evidence.flows),
        )

    def test_missing_snoop_and_ack_paths_are_reported_separately(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(
                omit=frozenset(("snoop", "completion_ack"))
            ),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE,)
            ),
        )

        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_SHARED)
        self.assertEqual(
            {"snoop", "completion_ack"},
            {
                gap.subject
                for gap in gaps
                if gap.kind is ChiCapabilityGapKind.FLOW
            },
        )

    def test_lifecycle_composition_is_an_explicit_system_fact(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
        )

        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_SHARED)
        self.assertEqual(1, len(gaps))
        self.assertIs(ChiCapabilityGapKind.SYSTEM, gaps[0].kind)
        self.assertEqual(
            (CHI_SYSTEM_CLEAN_READ_SHARED_LIFECYCLE,),
            gaps[0].missing,
        )


class ChiIssueHCleanReadUniqueCapabilityTest(unittest.TestCase):
    @staticmethod
    def contract():
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
                "snoopee": "rn1",
            },
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
        )

    @staticmethod
    def flows():
        return (
            ChiFlowCapability(
                "request",
                "rn0",
                "hn0",
                ChiChannelKind.REQ,
            ),
            ChiFlowCapability(
                "snoop",
                "hn0",
                "rn1",
                ChiChannelKind.SNP,
            ),
            ChiFlowCapability(
                "snoop_response",
                "rn1",
                "hn0",
                ChiChannelKind.RSP,
            ),
            ChiFlowCapability(
                "completion_data",
                "hn0",
                "rn0",
                ChiChannelKind.DAT,
            ),
            ChiFlowCapability(
                "completion_ack",
                "rn0",
                "hn0",
                ChiChannelKind.RSP,
            ),
        )

    def test_clean_read_unique_is_an_independent_closed_feature(self) -> None:
        participants = (
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
        )
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=participants,
            flows=self.flows(),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
            ),
        )

        evidence = resolved.require(CHI_FEATURE_CLEAN_READ_UNIQUE)
        self.assertFalse(evidence.dependencies)
        self.assertEqual(
            {
                "request",
                "snoop",
                "snoop_response",
                "completion_data",
                "completion_ack",
            },
            set(evidence.flows),
        )

    def test_shared_role_claims_do_not_imply_unique_behavior(self) -> None:
        participants = (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "rn1",
                CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES,
            ),
        )
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=participants,
            flows=self.flows(),
            system_capabilities=frozenset(
                (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
            ),
        )

        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE)
        self.assertEqual(
            {"rn0", "hn0", "rn1"},
            {
                gap.subject
                for gap in gaps
                if gap.kind is ChiCapabilityGapKind.PARTICIPANT
            },
        )


class ChiIssueHCleanReadUniqueRetryCapabilityTest(unittest.TestCase):
    @staticmethod
    def contract():
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
                "snoopee": "rn1",
            },
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,)),
        )

    @staticmethod
    def participants(*, retry: bool = True):
        return (
            ChiParticipantCapability(
                "rn0",
                (
                    CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES
                    if retry
                    else CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                ),
            ),
            ChiParticipantCapability(
                "hn0",
                (
                    CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES
                    if retry
                    else CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                ),
            ),
            ChiParticipantCapability(
                "rn1",
                CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
            ),
        )

    @staticmethod
    def flows(*, retry_response: bool = True):
        definitions = [
            ("request", "rn0", "hn0", ChiChannelKind.REQ),
            ("snoop", "hn0", "rn1", ChiChannelKind.SNP),
            ("snoop_response", "rn1", "hn0", ChiChannelKind.RSP),
            ("completion_data", "hn0", "rn0", ChiChannelKind.DAT),
            ("completion_ack", "rn0", "hn0", ChiChannelKind.RSP),
        ]
        if retry_response:
            definitions.append(
                ("retry_response", "hn0", "rn0", ChiChannelKind.RSP)
            )
        return tuple(
            ChiFlowCapability(name, source, target, channel)
            for name, source, target, channel in definitions
        )

    @staticmethod
    def system_capabilities(*, retry: bool = True):
        return frozenset(
            (
                CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                *(
                    (CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,)
                    if retry
                    else ()
                ),
            )
        )

    def test_retry_modifier_closes_over_clean_read_unique(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_CLEAN_READ_UNIQUE))
        evidence = resolved.require(
            CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
        )
        self.assertEqual(
            (CHI_FEATURE_CLEAN_READ_UNIQUE,),
            evidence.dependencies,
        )
        self.assertEqual(
            {"requester", "home"},
            set(evidence.participants),
        )
        self.assertEqual({"retry_response"}, set(evidence.flows))
        self.assertIs(
            CHI_CLEAN_READ_UNIQUE_RETRY_DEFINITION,
            CHI_BUILTIN_FEATURE_CATALOG.definitions[
                CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
            ],
        )

    def test_missing_reverse_rsp_only_removes_retry_modifier(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(retry_response=False),
            system_capabilities=self.system_capabilities(),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_CLEAN_READ_UNIQUE))
        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY)
        self.assertEqual(1, len(gaps))
        self.assertIs(ChiCapabilityGapKind.FLOW, gaps[0].kind)
        self.assertEqual("retry_response", gaps[0].subject)

    def test_base_participants_do_not_claim_retry_behavior(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(retry=False),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_CLEAN_READ_UNIQUE))
        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY)
        self.assertEqual(
            {"rn0", "hn0"},
            {
                gap.subject
                for gap in gaps
                if gap.kind is ChiCapabilityGapKind.PARTICIPANT
            },
        )
        self.assertTrue(
            all(
                gap.missing
                for gap in gaps
                if gap.kind is ChiCapabilityGapKind.PARTICIPANT
            )
        )

    def test_retry_composition_requires_explicit_system_fact(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(retry=False),
        )

        self.assertTrue(resolved.supports(CHI_FEATURE_CLEAN_READ_UNIQUE))
        gaps = resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY)
        self.assertEqual(1, len(gaps))
        self.assertIs(ChiCapabilityGapKind.SYSTEM, gaps[0].kind)
        self.assertEqual(
            (CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,),
            gaps[0].missing,
        )


class ChiIssueHCleanUniqueCleanPeersCapabilityTest(unittest.TestCase):
    @staticmethod
    def contract(*snoopees: str) -> ChiFeatureContract:
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
            },
            frozenset((CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,)),
            role_sets={"snoopee": frozenset(snoopees)},
        )

    @staticmethod
    def participants(*snoopees: str):
        return (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES,
            ),
            *(
                ChiParticipantCapability(
                    snoopee,
                    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES,
                )
                for snoopee in snoopees
            ),
        )

    @staticmethod
    def flows(
        *snoopees: str,
        snoop_response_channel: ChiChannelKind = ChiChannelKind.RSP,
    ):
        items = [
            (
                "request",
                "rn0",
                "hn0",
                ChiChannelKind.REQ,
            ),
            (
                "completion",
                "hn0",
                "rn0",
                ChiChannelKind.RSP,
            ),
            (
                "completion_ack",
                "rn0",
                "hn0",
                ChiChannelKind.RSP,
            ),
        ]
        for snoopee in snoopees:
            items.extend(
                (
                    (
                        f"snoop_{snoopee}",
                        "hn0",
                        snoopee,
                        ChiChannelKind.SNP,
                    ),
                    (
                        f"snoop_response_{snoopee}",
                        snoopee,
                        "hn0",
                        snoop_response_channel,
                    ),
                )
            )
        return tuple(
            ChiFlowCapability(name, source, target, channel)
            for name, source, target, channel in items
        )

    @staticmethod
    def system_capabilities():
        return frozenset(
            (CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,)
        )

    def test_clean_peer_profile_closes_five_non_data_flow_kinds(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1", "rn2"),
            participants=self.participants("rn1", "rn2"),
            flows=self.flows("rn1", "rn2"),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        self.assertFalse(evidence.dependencies)
        self.assertIs(
            CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION,
            CHI_BUILTIN_FEATURE_CATALOG.definitions[
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            ],
        )
        self.assertEqual(
            {
                "requester",
                "home",
                "snoopee[rn1]",
                "snoopee[rn2]",
            },
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "clean_unique_request",
                "clean_unique_completion",
                "clean_unique_completion_ack",
                "clean_unique_snoop[hn0->rn1]",
                "clean_unique_snoop[hn0->rn2]",
                "clean_unique_snoop_response[rn1->hn0]",
                "clean_unique_snoop_response[rn2->hn0]",
            },
            set(evidence.flows),
        )
        self.assertNotIn(
            ChiChannelKind.DAT,
            {flow.channel for flow in evidence.flows.values()},
        )
        self.assertEqual(
            {
                ChiChannelKind.REQ,
                ChiChannelKind.SNP,
                ChiChannelKind.RSP,
            },
            {
                requirement.channel
                for requirement
                in CHI_CLEAN_UNIQUE_CLEAN_PEERS_DEFINITION.flows
            },
        )

    def test_read_unique_capabilities_do_not_claim_clean_unique(
        self,
    ) -> None:
        participants = (
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
        )

        resolved = resolve_chi_capabilities(
            self.contract("rn1"),
            participants=participants,
            flows=self.flows("rn1"),
            system_capabilities=self.system_capabilities(),
        )

        self.assertEqual(
            {"rn0", "hn0", "rn1"},
            {
                gap.subject
                for gap in resolved.gaps(
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
                )
                if gap.kind is ChiCapabilityGapKind.PARTICIPANT
            },
        )

    def test_dirty_data_return_does_not_replace_clean_rsp_path(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1"),
            participants=self.participants("rn1"),
            flows=self.flows(
                "rn1",
                snoop_response_channel=ChiChannelKind.DAT,
            ),
            system_capabilities=self.system_capabilities(),
        )

        flow_gaps = tuple(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            )
            if gap.kind is ChiCapabilityGapKind.FLOW
        )
        self.assertEqual(1, len(flow_gaps))
        self.assertEqual(
            "clean_unique_snoop_response[rn1->hn0]",
            flow_gaps[0].subject,
        )

    def test_lifecycle_requires_explicit_system_capability(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1"),
            participants=self.participants("rn1"),
            flows=self.flows("rn1"),
        )

        system_gaps = tuple(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            )
            if gap.kind is ChiCapabilityGapKind.SYSTEM
        )
        self.assertEqual(1, len(system_gaps))
        self.assertEqual(
            (
                CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
            ),
            system_gaps[0].missing,
        )

    def test_empty_peer_set_closes_without_snoop_or_data_flows(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        )
        self.assertEqual(
            {
                "clean_unique_request",
                "clean_unique_completion",
                "clean_unique_completion_ack",
            },
            set(evidence.flows),
        )


class ChiIssueHCleanUniqueSharedDirtyPeerCapabilityTest(
    unittest.TestCase
):
    @staticmethod
    def contract(*snoopees: str) -> ChiFeatureContract:
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
            },
            frozenset(
                (CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,)
            ),
            role_sets={"snoopee": frozenset(snoopees)},
        )

    @staticmethod
    def participants(
        *snoopees: str,
        home_memory_update: bool = True,
    ):
        home_extension = (
            CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES
        )
        if not home_memory_update:
            home_extension = home_extension - frozenset(
                (CHI_HOME_PASS_DIRTY_MEMORY_UPDATE,)
            )
        return (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES
                | home_extension,
            ),
            *(
                ChiParticipantCapability(
                    snoopee,
                    CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES
                    | (
                        CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES
                    ),
                )
                for snoopee in snoopees
            ),
        )

    @staticmethod
    def flows(*snoopees: str, include_data: bool = True):
        flows = list(
            ChiIssueHCleanUniqueCleanPeersCapabilityTest.flows(
                *snoopees
            )
        )
        if include_data:
            flows.extend(
                ChiFlowCapability(
                    f"snoop_data_{snoopee}",
                    snoopee,
                    "hn0",
                    ChiChannelKind.DAT,
                )
                for snoopee in snoopees
            )
        return tuple(flows)

    @staticmethod
    def system_capabilities():
        return frozenset(
            (
                CHI_SYSTEM_CLEAN_UNIQUE_CLEAN_PEERS_LIFECYCLE,
                CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE,
            )
        )

    def test_extension_adds_dat_flow_to_clean_unique_base(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1", "rn2"),
            participants=self.participants("rn1", "rn2"),
            flows=self.flows("rn1", "rn2"),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
        )
        self.assertEqual(
            (CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,),
            evidence.dependencies,
        )
        self.assertIs(
            CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION,
            CHI_BUILTIN_FEATURE_CATALOG.definitions[
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            ],
        )
        self.assertEqual(
            {
                "home",
                "snoopee[rn1]",
                "snoopee[rn2]",
            },
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "clean_unique_snoop_data[rn1->hn0]",
                "clean_unique_snoop_data[rn2->hn0]",
            },
            set(evidence.flows),
        )
        self.assertEqual(
            (ChiChannelKind.DAT,),
            tuple(
                requirement.channel
                for requirement in
                CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_DEFINITION.flows
            ),
        )
        self.assertTrue(
            resolved.supports(CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS)
        )

    def test_missing_snoopee_dat_path_is_a_flow_gap(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1"),
            participants=self.participants("rn1"),
            flows=self.flows("rn1", include_data=False),
            system_capabilities=self.system_capabilities(),
        )

        gaps = tuple(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            )
            if gap.kind is ChiCapabilityGapKind.FLOW
        )
        self.assertEqual(1, len(gaps))
        self.assertEqual(
            "clean_unique_snoop_data[rn1->hn0]",
            gaps[0].subject,
        )
        self.assertTrue(
            resolved.supports(CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS)
        )

    def test_home_must_claim_pass_dirty_memory_update(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1"),
            participants=self.participants(
                "rn1",
                home_memory_update=False,
            ),
            flows=self.flows("rn1"),
            system_capabilities=self.system_capabilities(),
        )

        gap = next(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            )
            if gap.kind is ChiCapabilityGapKind.PARTICIPANT
            and gap.subject == "hn0"
        )
        self.assertEqual(
            (CHI_HOME_PASS_DIRTY_MEMORY_UPDATE,),
            gap.missing,
        )

    def test_shared_dirty_profile_requires_a_peer(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        gap = next(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            )
            if gap.kind is ChiCapabilityGapKind.ROLE
        )
        self.assertEqual("snoopee", gap.subject)


class ChiIssueHDirtyWriteBackCapabilityTest(unittest.TestCase):
    def test_writeback_closes_two_roles_and_three_protocol_flows(self) -> None:
        contract = ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
            },
            frozenset((CHI_FEATURE_DIRTY_WRITEBACK,)),
        )
        participants = (
            ChiParticipantCapability(
                "rn0",
                CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
            ),
        )
        flows = (
            ChiFlowCapability(
                "writeback_request_path",
                "rn0",
                "hn0",
                ChiChannelKind.REQ,
            ),
            ChiFlowCapability(
                "dbid_response_path",
                "hn0",
                "rn0",
                ChiChannelKind.RSP,
            ),
            ChiFlowCapability(
                "copyback_data_path",
                "rn0",
                "hn0",
                ChiChannelKind.DAT,
            ),
        )

        resolved = resolve_chi_capabilities(
            contract,
            participants=participants,
            flows=flows,
            system_capabilities=frozenset(
                (CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,)
            ),
        )

        evidence = resolved.require(CHI_FEATURE_DIRTY_WRITEBACK)
        self.assertEqual(
            (),
            evidence.dependencies,
        )
        self.assertEqual(
            {"requester", "home"},
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "writeback_request",
                "writeback_dbid_response",
                "writeback_copyback_data",
            },
            set(evidence.flows),
        )


class ChiIssueHFiniteSnoopeeSetCapabilityTest(unittest.TestCase):
    @staticmethod
    def contract(*snoopees: str):
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
            },
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
            role_sets={"snoopee": frozenset(snoopees)},
        )

    @staticmethod
    def participants(*snoopees: str):
        return (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
            ),
            *(
                ChiParticipantCapability(
                    snoopee,
                    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
                )
                for snoopee in snoopees
            ),
        )

    @staticmethod
    def flows(*snoopees: str, omit: frozenset[tuple[str, str]] = frozenset()):
        definitions = [
            ("request", "rn0", "hn0", ChiChannelKind.REQ),
            ("completion_data", "hn0", "rn0", ChiChannelKind.DAT),
            ("completion_ack", "rn0", "hn0", ChiChannelKind.RSP),
        ]
        for snoopee in snoopees:
            definitions.extend(
                (
                    (
                        f"snoop_{snoopee}",
                        "hn0",
                        snoopee,
                        ChiChannelKind.SNP,
                    ),
                    (
                        f"snoop_response_{snoopee}",
                        snoopee,
                        "hn0",
                        ChiChannelKind.RSP,
                    ),
                )
            )
        return tuple(
            ChiFlowCapability(name, source, target, channel)
            for name, source, target, channel in definitions
            if (source, target) not in omit
        )

    @staticmethod
    def system_capabilities():
        return frozenset((CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,))

    def test_every_declared_snoopee_closes_capability_and_both_paths(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1", "rn2"),
            participants=self.participants("rn1", "rn2"),
            flows=self.flows("rn1", "rn2"),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(CHI_FEATURE_CLEAN_READ_UNIQUE)
        self.assertEqual(
            {
                "requester",
                "home",
                "snoopee[rn1]",
                "snoopee[rn2]",
            },
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "request",
                "completion_data",
                "completion_ack",
                "snoop[hn0->rn1]",
                "snoop[hn0->rn2]",
                "snoop_response[rn1->hn0]",
                "snoop_response[rn2->hn0]",
            },
            set(evidence.flows),
        )

    def test_one_missing_return_path_names_the_exact_snoopee(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1", "rn2"),
            participants=self.participants("rn1", "rn2"),
            flows=self.flows(
                "rn1",
                "rn2",
                omit=frozenset((("rn2", "hn0"),)),
            ),
            system_capabilities=self.system_capabilities(),
        )

        flow_gaps = tuple(
            gap
            for gap in resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE)
            if gap.kind is ChiCapabilityGapKind.FLOW
        )
        self.assertEqual(1, len(flow_gaps))
        self.assertEqual(
            "snoop_response[rn2->hn0]",
            flow_gaps[0].subject,
        )

    def test_one_missing_participant_claim_names_the_exact_snoopee(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract("rn1", "rn2"),
            participants=self.participants("rn1"),
            flows=self.flows("rn1", "rn2"),
            system_capabilities=self.system_capabilities(),
        )

        participant_gaps = tuple(
            gap
            for gap in resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE)
            if gap.kind is ChiCapabilityGapKind.PARTICIPANT
        )
        self.assertEqual(1, len(participant_gaps))
        self.assertEqual("rn2", participant_gaps[0].subject)

    def test_role_flow_expansion_is_shared_and_deterministic(self) -> None:
        snoop = next(
            flow
            for flow in CHI_CLEAN_READ_UNIQUE_DEFINITION.flows
            if flow.name == "snoop"
        )
        obligations = bind_chi_flow_requirement(
            self.contract("rn2", "rn1"),
            snoop,
        )

        self.assertIsNotNone(obligations)
        self.assertEqual(
            (
                ("snoop[hn0->rn1]", "hn0", "rn1"),
                ("snoop[hn0->rn2]", "hn0", "rn2"),
            ),
            tuple(
                (item.key, item.source, item.target)
                for item in obligations or ()
            ),
        )

    def test_two_set_endpoints_have_unambiguous_evidence_keys(self) -> None:
        contract = ChiFeatureContract(
            {},
            role_sets={
                "sources": frozenset(("a", "a->b")),
                "targets": frozenset(("b->c", "c")),
            },
        )
        requirement = ChiFlowRequirement(
            "fan[out]",
            "sources",
            "targets",
            ChiChannelKind.REQ,
        )

        obligations = bind_chi_flow_requirement(contract, requirement)

        self.assertIsNotNone(obligations)
        keys = tuple(item.key for item in obligations or ())
        self.assertEqual(4, len(keys))
        self.assertEqual(4, len(set(keys)))
        self.assertTrue(all("%" in key for key in keys))

    def test_explicit_empty_peer_domain_closes_vacuously(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(CHI_FEATURE_CLEAN_READ_UNIQUE)
        self.assertEqual({"requester", "home"}, set(evidence.participants))
        self.assertEqual(
            {"request", "completion_data", "completion_ack"},
            set(evidence.flows),
        )

    def test_omitting_the_domain_is_not_the_same_as_an_empty_domain(
        self,
    ) -> None:
        contract = ChiFeatureContract(
            {"requester": "rn0", "home": "hn0"},
            frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
        )
        resolved = resolve_chi_capabilities(
            contract,
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        self.assertIn(
            "snoopee",
            {
                gap.subject
                for gap in resolved.gaps(CHI_FEATURE_CLEAN_READ_UNIQUE)
                if gap.kind is ChiCapabilityGapKind.ROLE
            },
        )


class ChiIssueHCapabilityProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ChiReadNoSnpDirectProfile(
            requester_node_id=0x07,
            home_node_id=0x21,
            data_width=128,
            outstanding_capacity=2,
        )
        self.requester = ChiReadNoSnpDirectLedger(
            "rn.reads", self.profile
        )
        self.home = ChiDirectHomeNode(
            "home",
            self.profile,
            lambda request: request.address,
            request_capacity=1,
        )

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
        name: str, channel: ChiChannelKind
    ) -> ChiTransportLinkProfile:
        common = {
            "clock": "chi_clk",
            "activation_observation": f"{name}.active",
        }
        if channel is ChiChannelKind.REQ:
            return ChiTransportLinkProfile(
                request=ChiReqChannelProfile(
                    representation=ChiIssueHReqProfile(),
                    observation=f"{name}.req",
                ),
                data=None,
                **common,
            )
        if channel is ChiChannelKind.RSP:
            return ChiTransportLinkProfile(
                request=None,
                response=ChiRspChannelProfile(
                    representation=ChiIssueHRspProfile(),
                    observation=f"{name}.rsp",
                ),
                **common,
            )
        return ChiTransportLinkProfile(
            request=None,
            data=ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                observation=f"{name}.dat",
            ),
            **common,
        )

    def build_direct(
        self,
        *,
        include_response: bool = True,
        response_runtime_channel: ChiChannelKind = ChiChannelKind.RSP,
    ):
        builder = SystemProtocolBuilder("chi_capability_projection")
        rn_ports = {
            "tx_req": self.port("tx_req", TransportDirection.TRANSMIT),
            "rx_dat": self.port("rx_dat", TransportDirection.RECEIVE),
        }
        home_ports = {
            "rx_req": self.port("rx_req", TransportDirection.RECEIVE),
            "tx_dat": self.port("tx_dat", TransportDirection.TRANSMIT),
        }
        if include_response:
            rn_ports["rx_rsp"] = self.port(
                "rx_rsp", TransportDirection.RECEIVE
            )
            home_ports["tx_rsp"] = self.port(
                "tx_rsp", TransportDirection.TRANSMIT
            )
        builder.add_dut(VirtualDut("rn", rn_ports))
        builder.add_dut(VirtualDut("home", home_ports))
        connections = [
            (
                "request",
                "rn",
                "tx_req",
                "home",
                "rx_req",
                ChiChannelKind.REQ,
            ),
            (
                "data",
                "home",
                "tx_dat",
                "rn",
                "rx_dat",
                ChiChannelKind.DAT,
            ),
        ]
        if include_response:
            connections.append(
                (
                    "response",
                    "home",
                    "tx_rsp",
                    "rn",
                    "rx_rsp",
                    response_runtime_channel,
                )
            )
        for name, tx_dut, tx_port, rx_dut, rx_port, channel in connections:
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                VirtualDutPortRef(tx_dut, tx_port),
                VirtualDutPortRef(rx_dut, rx_port),
                profile=self.link_profile(name, channel),
            )
        system = builder.build().elaborate()
        network = ChiTransportNetworkSession(system)
        duts = system.spec.virtual_duts
        port_binding = ChiParticipantPortBinding
        requester_ports = [
            port_binding(
                duts["rn"].port("tx_req"),
                frozenset((ChiChannelKind.REQ,)),
            ),
            port_binding(
                duts["rn"].port("rx_dat"),
                frozenset((ChiChannelKind.DAT,)),
            ),
        ]
        home_binding_ports = [
            port_binding(
                duts["home"].port("rx_req"),
                frozenset((ChiChannelKind.REQ,)),
            ),
            port_binding(
                duts["home"].port("tx_dat"),
                frozenset((ChiChannelKind.DAT,)),
            ),
        ]
        if include_response:
            requester_ports.append(
                port_binding(
                    duts["rn"].port("rx_rsp"),
                    frozenset((ChiChannelKind.RSP,)),
                )
            )
            home_binding_ports.append(
                port_binding(
                    duts["home"].port("tx_rsp"),
                    frozenset((ChiChannelKind.RSP,)),
                )
            )
        requester = ChiParticipantBinding(
            "requester",
            duts["rn"],
            self.requester,
            tuple(requester_ports),
            frozenset((self.profile.requester_node_id,)),
        )
        home = ChiParticipantBinding(
            "home",
            duts["home"],
            self.home,
            tuple(home_binding_ports),
            frozenset((self.profile.home_node_id,)),
        )
        return network, (requester, home)

    @staticmethod
    def feature_contract():
        return ChiFeatureContract(
            {"requester": "requester", "home": "home"},
            frozenset((CHI_FEATURE_REQUEST_RETRY,)),
        )

    @staticmethod
    def participant_capabilities():
        return (
            ChiParticipantCapability(
                "requester",
                CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES,
            ),
            ChiParticipantCapability(
                "home",
                CHI_REQUEST_RETRY_HOME_CAPABILITIES,
            ),
        )

    def test_projector_closes_builtin_flows_from_executable_network(self) -> None:
        network, bindings = self.build_direct()
        projection = project_chi_flow_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
        )

        self.assertEqual((), projection.gaps)
        self.assertEqual(
            {
                ("requester", "home", ChiChannelKind.REQ),
                ("home", "requester", ChiChannelKind.DAT),
                ("home", "requester", ChiChannelKind.RSP),
            },
            {
                (flow.source, flow.target, flow.channel)
                for flow in projection.flows
            },
        )
        self.assertEqual(
            ("request",),
            next(
                flow.connections
                for flow in projection.flows
                if flow.channel is ChiChannelKind.REQ
            ),
        )

        resolved = resolve_projected_chi_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
            participant_capabilities=self.participant_capabilities(),
        )
        self.assertTrue(resolved.supports(CHI_FEATURE_READ_NO_SNP))
        self.assertTrue(resolved.supports(CHI_FEATURE_REQUEST_RETRY))

    def test_selected_target_identity_excludes_other_owned_node_ids(
        self,
    ) -> None:
        network, bindings = self.build_direct()
        requester, home = bindings
        selected_home_id = self.profile.home_node_id
        compound_home = ChiParticipantBinding(
            home.name,
            home.dut,
            home.component,
            home.ports,
            frozenset((selected_home_id, 1 << 20)),
        )
        feature = ChiFeatureKey("chi.feature.test.request_path")
        catalog = ChiFeatureCatalog(
            {
                feature: ChiFeatureDefinition(
                    feature,
                    flows=(
                        ChiFlowRequirement(
                            "request",
                            "requester",
                            "home",
                            ChiChannelKind.REQ,
                        ),
                    ),
                )
            }
        )
        contract = ChiFeatureContract(
            {"requester": "requester", "home": "home"},
            frozenset((feature,)),
        )

        projection = project_chi_flow_capabilities(
            network,
            contract,
            bindings=(requester, compound_home),
            catalog=catalog,
            target_node_id_by_participant={
                "home": selected_home_id,
            },
        )

        self.assertEqual((), projection.gaps)
        self.assertEqual(1, len(projection.flows))

    def test_projector_proves_every_member_of_a_finite_target_set(
        self,
    ) -> None:
        builder = SystemProtocolBuilder("chi_capability_target_set")
        requester_ports = {
            "tx_req_1": self.port(
                "tx_req_1", TransportDirection.TRANSMIT
            ),
            "tx_req_2": self.port(
                "tx_req_2", TransportDirection.TRANSMIT
            ),
        }
        builder.add_dut(VirtualDut("rn", requester_ports))
        builder.add_dut(
            VirtualDut(
                "home1",
                {
                    "rx_req": self.port(
                        "rx_req", TransportDirection.RECEIVE
                    )
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "home2",
                {
                    "rx_req": self.port(
                        "rx_req", TransportDirection.RECEIVE
                    )
                },
            )
        )
        for index in (1, 2):
            builder.connect_transport(
                f"request_{index}",
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                VirtualDutPortRef("rn", f"tx_req_{index}"),
                VirtualDutPortRef(f"home{index}", "rx_req"),
                profile=self.link_profile(
                    f"request_{index}",
                    ChiChannelKind.REQ,
                ),
            )
        system = builder.build().elaborate()
        network = ChiTransportNetworkSession(system)
        duts = system.spec.virtual_duts
        port_binding = ChiParticipantPortBinding
        requester = ChiParticipantBinding(
            "requester",
            duts["rn"],
            self.requester,
            tuple(
                port_binding(
                    duts["rn"].port(f"tx_req_{index}"),
                    frozenset((ChiChannelKind.REQ,)),
                )
                for index in (1, 2)
            ),
            frozenset((self.profile.requester_node_id,)),
        )
        homes = tuple(
            ChiParticipantBinding(
                f"home{index}",
                duts[f"home{index}"],
                self.home,
                (
                    port_binding(
                        duts[f"home{index}"].port("rx_req"),
                        frozenset((ChiChannelKind.REQ,)),
                    ),
                ),
                frozenset((self.profile.home_node_id + index,)),
            )
            for index in (1, 2)
        )
        feature = ChiFeatureKey("chi.feature.test.finite_targets")
        catalog = ChiFeatureCatalog(
            {
                feature: ChiFeatureDefinition(
                    feature,
                    flows=(
                        ChiFlowRequirement(
                            "request",
                            "requester",
                            "homes",
                            ChiChannelKind.REQ,
                        ),
                    ),
                )
            }
        )
        contract = ChiFeatureContract(
            {"requester": "requester"},
            frozenset((feature,)),
            role_sets={"homes": frozenset(("home1", "home2"))},
        )

        projection = project_chi_flow_capabilities(
            network,
            contract,
            bindings=(requester, *homes),
            catalog=catalog,
        )

        self.assertEqual((), projection.gaps)
        self.assertEqual(
            {
                ("requester", "home1"),
                ("requester", "home2"),
            },
            {(flow.source, flow.target) for flow in projection.flows},
        )
        self.assertEqual(
            {
                f"{feature.name}:request[requester->home1]",
                f"{feature.name}:request[requester->home2]",
            },
            set(projection.flow_by_requirement),
        )

    def test_missing_runtime_channel_is_not_promoted_from_topology(self) -> None:
        network, bindings = self.build_direct(include_response=False)
        projection = project_chi_flow_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
        )

        response_gaps = tuple(
            gap
            for gap in projection.gaps
            if gap.channel is ChiChannelKind.RSP
        )
        self.assertEqual(1, len(response_gaps))
        self.assertIs(
            ChiFlowProjectionGapKind.PORT,
            response_gaps[0].kind,
        )
        resolved = resolve_projected_chi_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
            participant_capabilities=self.participant_capabilities(),
        )
        self.assertTrue(resolved.supports(CHI_FEATURE_READ_NO_SNP))
        self.assertFalse(resolved.supports(CHI_FEATURE_REQUEST_RETRY))

    def test_topology_edge_with_wrong_runtime_channel_reports_channel_gap(
        self,
    ) -> None:
        network, bindings = self.build_direct(
            response_runtime_channel=ChiChannelKind.DAT
        )

        projection = project_chi_flow_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
        )

        response_gaps = tuple(
            gap
            for gap in projection.gaps
            if gap.channel is ChiChannelKind.RSP
        )
        self.assertEqual(1, len(response_gaps))
        self.assertIs(
            ChiFlowProjectionGapKind.CHANNEL,
            response_gaps[0].kind,
        )
        self.assertIn("topology connection 'response' exists", response_gaps[0].reason)
        resolved = resolve_projected_chi_capabilities(
            network,
            self.feature_contract(),
            bindings=bindings,
            participant_capabilities=self.participant_capabilities(),
        )
        self.assertFalse(resolved.supports(CHI_FEATURE_REQUEST_RETRY))


if __name__ == "__main__":
    unittest.main()
