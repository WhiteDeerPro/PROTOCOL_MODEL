from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.participants.capability import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_HOME_COPY_AT_HOME_COMP_DATA_PRODUCE,
    CHI_HOME_WRITE_EVICT_FULL_COMP_PRODUCE,
    CHI_HOME_WRITE_EVICT_FULL_COPY_AT_HOME_ACCEPT,
    CHI_REQUESTER_COPY_AT_HOME_PROVENANCE_CACHE,
    CHI_REQUESTER_WRITE_EVICT_FULL_COMP_ACCEPT,
    CHI_REQUESTER_WRITE_EVICT_FULL_COPY_AT_HOME_ISSUE,
    CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES,
    CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES,
    ChiCapabilityKey,
    ChiParticipantCapability,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.system.capability import (
    CHI_BUILTIN_FEATURE_CATALOG,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_WRITE_EVICT_FULL,
    CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE,
    CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,
    CHI_WRITE_EVICT_FULL_COPY_AT_HOME_DEFINITION,
    CHI_WRITE_EVICT_FULL_DEFINITION,
    ChiCapabilityGapKind,
    ChiFeatureContract,
    ChiFlowCapability,
    resolve_chi_capabilities,
)


class ChiIssueHWriteEvictFullCopyAtHomeCapabilityTest(
    unittest.TestCase
):
    @staticmethod
    def contract() -> ChiFeatureContract:
        return ChiFeatureContract(
            {
                "requester": "rn0",
                "home": "hn0",
            },
            frozenset(
                (CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME,)
            ),
            role_sets={"snoopee": frozenset()},
        )

    @staticmethod
    def participants(
        *,
        requester_modifier: frozenset[ChiCapabilityKey] = (
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES
        ),
        home_modifier: frozenset[ChiCapabilityKey] = (
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES
        ),
    ) -> tuple[ChiParticipantCapability, ...]:
        return (
            ChiParticipantCapability(
                "rn0",
                CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                | CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES
                | requester_modifier,
            ),
            ChiParticipantCapability(
                "hn0",
                CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                | CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES
                | home_modifier,
            ),
        )

    @staticmethod
    def flows() -> tuple[ChiFlowCapability, ...]:
        return (
            ChiFlowCapability(
                "request_path",
                "rn0",
                "hn0",
                ChiChannelKind.REQ,
            ),
            ChiFlowCapability(
                "home_response_path",
                "hn0",
                "rn0",
                ChiChannelKind.RSP,
            ),
            ChiFlowCapability(
                "read_completion_data_path",
                "hn0",
                "rn0",
                ChiChannelKind.DAT,
            ),
            ChiFlowCapability(
                "requester_response_path",
                "rn0",
                "hn0",
                ChiChannelKind.RSP,
            ),
            ChiFlowCapability(
                "copyback_data_path",
                "rn0",
                "hn0",
                ChiChannelKind.DAT,
            ),
        )

    @staticmethod
    def system_capabilities() -> frozenset[ChiCapabilityKey]:
        return frozenset(
            (
                CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                CHI_SYSTEM_WRITE_EVICT_FULL_LIFECYCLE,
                CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE,
            )
        )

    def test_modifier_depends_on_acquisition_and_base_copyback(
        self,
    ) -> None:
        definition = CHI_WRITE_EVICT_FULL_COPY_AT_HOME_DEFINITION
        self.assertEqual(
            frozenset(
                (
                    CHI_FEATURE_CLEAN_READ_UNIQUE,
                    CHI_FEATURE_WRITE_EVICT_FULL,
                )
            ),
            definition.dependencies,
        )
        self.assertEqual(
            (
                (
                    "write_evict_copy_at_home_response",
                    "home",
                    "requester",
                    ChiChannelKind.RSP,
                ),
                (
                    "write_evict_copy_at_home_completion_ack",
                    "requester",
                    "home",
                    ChiChannelKind.RSP,
                ),
            ),
            tuple(
                (
                    flow.name,
                    flow.source_role,
                    flow.target_role,
                    flow.channel,
                )
                for flow in definition.flows
            ),
        )
        self.assertTrue(definition.requires_coherence_domain)
        self.assertIs(
            definition,
            CHI_BUILTIN_FEATURE_CATALOG.definitions[
                CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME
            ],
        )

    def test_base_write_evict_full_remains_the_cah_zero_path(
        self,
    ) -> None:
        self.assertFalse(CHI_WRITE_EVICT_FULL_DEFINITION.dependencies)
        self.assertEqual(
            (
                "write_evict_request",
                "write_evict_dbid_response",
                "write_evict_copyback_data",
            ),
            tuple(
                flow.name
                for flow in CHI_WRITE_EVICT_FULL_DEFINITION.flows
            ),
        )

    def test_modifier_closes_with_both_home_terminal_paths(self) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities(),
        )

        evidence = resolved.require(
            CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME
        )
        self.assertEqual(
            (
                CHI_FEATURE_CLEAN_READ_UNIQUE,
                CHI_FEATURE_WRITE_EVICT_FULL,
            ),
            evidence.dependencies,
        )
        self.assertEqual(
            {"requester", "home"},
            set(evidence.participants),
        )
        self.assertEqual(
            {
                "write_evict_copy_at_home_response",
                "write_evict_copy_at_home_completion_ack",
            },
            set(evidence.flows),
        )

    def test_incremental_role_claims_are_explicit_and_minimal(
        self,
    ) -> None:
        self.assertEqual(
            frozenset(
                (
                    CHI_REQUESTER_COPY_AT_HOME_PROVENANCE_CACHE,
                    CHI_REQUESTER_WRITE_EVICT_FULL_COPY_AT_HOME_ISSUE,
                    CHI_REQUESTER_WRITE_EVICT_FULL_COMP_ACCEPT,
                )
            ),
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES,
        )
        self.assertEqual(
            frozenset(
                (
                    CHI_HOME_COPY_AT_HOME_COMP_DATA_PRODUCE,
                    CHI_HOME_WRITE_EVICT_FULL_COPY_AT_HOME_ACCEPT,
                    CHI_HOME_WRITE_EVICT_FULL_COMP_PRODUCE,
                )
            ),
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES,
        )

    def test_each_incremental_atomic_capability_is_required(self) -> None:
        requester_capabilities = (
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES
        )
        home_capabilities = (
            CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES
        )
        cases = (
            (
                "rn0",
                "requester",
                requester_capabilities,
            ),
            (
                "hn0",
                "home",
                home_capabilities,
            ),
        )
        for participant, role, capabilities in cases:
            for missing in capabilities:
                with self.subTest(role=role, missing=missing):
                    arguments = {
                        "requester_modifier": requester_capabilities,
                        "home_modifier": home_capabilities,
                    }
                    arguments[f"{role}_modifier"] = capabilities - {
                        missing
                    }
                    resolved = resolve_chi_capabilities(
                        self.contract(),
                        participants=self.participants(**arguments),
                        flows=self.flows(),
                        system_capabilities=self.system_capabilities(),
                    )

                    gaps = tuple(
                        gap
                        for gap in resolved.gaps(
                            CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME
                        )
                        if gap.kind
                        is ChiCapabilityGapKind.PARTICIPANT
                    )
                    self.assertEqual(1, len(gaps))
                    self.assertEqual(participant, gaps[0].subject)
                    self.assertEqual((missing,), gaps[0].missing)

    def test_modifier_lifecycle_is_an_independent_system_fact(
        self,
    ) -> None:
        resolved = resolve_chi_capabilities(
            self.contract(),
            participants=self.participants(),
            flows=self.flows(),
            system_capabilities=self.system_capabilities()
            - {
                CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE
            },
        )

        gaps = tuple(
            gap
            for gap in resolved.gaps(
                CHI_FEATURE_WRITE_EVICT_FULL_COPY_AT_HOME
            )
            if gap.kind is ChiCapabilityGapKind.SYSTEM
        )
        self.assertEqual(1, len(gaps))
        self.assertEqual(
            (CHI_SYSTEM_WRITE_EVICT_FULL_COPY_AT_HOME_LIFECYCLE,),
            gaps[0].missing,
        )


if __name__ == "__main__":
    unittest.main()
